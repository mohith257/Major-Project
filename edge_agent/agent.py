"""
edge_agent/agent.py

This module IS the "agentic" layer of Agentic FedGrid.

Everything else in this project -- the TabularTransformer classifier, the
LoRA trainer, the blocklist actuator, the HTTPS client that talks to AWS --
is a tool. None of them decide anything on their own. EdgeAgent is the
controller that owns the loop and picks, autonomously and per-device, which
tool to invoke and when. No fixed schedule, no command from the cloud
telling it what to do next -- that autonomy is what makes this "agentic"
rather than "an automated pipeline" (see memory.md §2).

perceive : score the next incoming flow record with the current model
decide   : given that score plus recent local history, choose ONE action
act      : execute the chosen action via the relevant tool
reflect  : record the decision + rationale, for the explainability dashboard

`self.model` is expected to be an `edge_agent.inference.InferenceModel` --
its `.infer(flow_record)` handles the row->tensor encoding, and `act()`
below reaches through `.model.encoder`/`.model.model` to compute an
attention-rollout explanation (model/explain.py, Objective 5) for every
BLOCK/ALERT decision, so the incident log carries WHICH features drove the
call, not just a confidence number.
"""
import copy
import ipaddress
import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum, auto

from edge_agent.bandit import INVESTIGATE_COST, action_cost
from edge_agent.bandit import context as bandit_context
from edge_agent.flow_history import FlowHistory
from edge_agent.policy import DEFAULT_COSTS, choose_action, gated_load, threshold_action, update_costs
from model.explain import attention_rollout


class Action(Enum):
    NOOP = auto()
    ALERT = auto()
    BLOCK = auto()
    RETRAIN = auto()
    SYNC_DOWNLOAD = auto()
    REJECT_GLOBAL = auto()
    ROLLBACK = auto()
    INVESTIGATE = auto()
    ESCALATE = auto()
    FL_UPLOAD = auto()


@dataclass
class Decision:
    action: Action
    reason: str
    confidence: float = None
    source_ip: str = None


class EdgeAgent:
    """policy="cost": cost-aware action choice (edge_agent/policy.py);
    policy="threshold": the original fixed-threshold rule, kept for comparison.
    gate_updates=True: a global model is adopted only if it doesn't hurt this
    device's own held-out accuracy/FPR. share_intel=True: IPs other devices
    blocked are pulled from the cloud and escalated faster here."""

    def __init__(self, device_id, model, drift_monitor, self_eval_trigger,
                 trainer, actuator, comms, block_confidence=0.9,
                 sync_poll_interval=15, retrain_cooldown=300, self_eval_interval=60,
                 policy="cost", costs=None, gate_updates=True, share_intel=True,
                 exception_ttl=1800, investigator=None, history=None, bandit=None,
                 intel_scope=None, fed_interval=0):
        self.device_id = device_id
        # fed_interval: seconds between scheduled federated contributions
        # (0 = only upload on RETRAIN, the old behavior). Contributions fire
        # on wall-clock boundaries (now // fed_interval), so every node
        # trains and uploads in the same window and rounds fill up together.
        # Under the old behavior a healthy node never retrained, so it never
        # uploaded, and rounds ran with one participant or none.
        self.fed_interval = fed_interval
        self._fed_slot = int(time.time() // fed_interval) if fed_interval else None
        # run_step (capture thread) and tick (housekeeping thread) both touch
        # the model, actuator and peer intel
        self.lock = threading.RLock()
        # intel_scope: an ipaddress network (or None). When set, a peer's
        # BLOCK is acted on pre-emptively only for source IPs inside it --
        # a device shouldn't firewall an address it can never receive a
        # packet from (e.g. dataset IPs from offline replay that aren't
        # hosts on this network). Peer intel outside the scope is still
        # tracked in peer_flagged and still escalates a flow that does
        # arrive; it just isn't blocked sight-unseen.
        self.intel_scope = intel_scope
        # investigator: edge_agent/investigator.Investigator or None. When
        # set, flows the cost policy would only ALERT on are investigated by
        # Claude over this device's per-source flow history instead.
        self.investigator = investigator
        # policy="bandit": edge_agent/bandit.LinUCB picks the action from the
        # score + the source's history, and learns from labels that arrive
        # later (analyst feedback, or the investigator's verdict as a weak label)
        self.bandit = bandit
        self.history = history or (investigator.history if investigator else None)
        if bandit is not None and self.history is None:
            self.history = FlowHistory()
        self.pending = {}  # ip -> deque of (context, chosen action, made an LLM call)
        self._last_p_attack = None
        self._last_ctx = self._last_choice = None
        self._last_submitted = False
        self.model = model
        self.drift_monitor = drift_monitor
        self.self_eval_trigger = self_eval_trigger
        self.trainer = trainer
        self.actuator = actuator
        self.comms = comms
        self.block_confidence = block_confidence
        self.sync_poll_interval = sync_poll_interval
        self.policy = policy
        self.costs = dict(costs or DEFAULT_COSTS)
        self.gate_updates = gate_updates
        self.share_intel = share_intel
        self.peer_flagged = set()
        # analyst-confirmed false positives: ip -> time until which a BLOCK
        # verdict on it is downgraded to ALERT (learned exception, expires)
        self.exception_ttl = exception_ttl
        self.exceptions = {}
        self._last_sync_check = float("-inf")
        # Without these two, a device whose own-buffer accuracy stays under the
        # self-eval floor after retraining re-scored its whole buffer (~100K
        # rows) on EVERY benign flow and retrained + uploaded on every one.
        self.retrain_cooldown = retrain_cooldown
        self.self_eval_interval = self_eval_interval
        self._last_retrain = float("-inf")
        self._last_self_eval = float("-inf")
        self.log = []

    def perceive(self, flow_record):
        """Score one incoming (unlabeled) flow. Returns (pred_class, confidence, p_attack)."""
        probs = self.model.infer(flow_record).softmax(dim=-1)
        confidence, pred_class = probs.max(dim=-1)
        confidence = confidence.item()
        self.drift_monitor.update(confidence)
        return pred_class.item(), confidence, probs[1].item()

    def decide(self, p_attack, confidence, flow_record, now) -> Decision:
        """Pick exactly one action for this flow given perception + local state."""
        src = getattr(flow_record, "src_ip", None)
        if self.policy == "bandit":
            self._last_choice = None
            if src and self.actuator.is_blocked(src, now):  # a real DROP would hide these
                return Decision(Action.NOOP, reason="source already blocked", confidence=confidence)
            self._last_ctx = bandit_context(self.history, src, p_attack, now, src in self.peer_flagged)
            can_investigate = self.investigator is not None and src
            action = self.bandit.choose(self._last_ctx, allowed=None if can_investigate
                                        else ["NOOP", "ALERT", "BLOCK"])
            self._last_choice = action
        else:
            action = (choose_action(p_attack, self.costs) if self.policy == "cost"
                      else threshold_action(p_attack, self.block_confidence))
        # cost/threshold policies hand their whole ALERT band to the
        # investigator; the bandit decides for itself when to investigate
        if action == "ALERT" and self.policy != "bandit" and self.investigator and src:
            action = "INVESTIGATE"
        if action == "ALERT" and src in self.peer_flagged:
            return Decision(Action.BLOCK, reason="suspicious flow from an IP a peer device blocked",
                            confidence=confidence, source_ip=src)
        if action == "BLOCK" and self.exceptions.get(src, float("-inf")) > now:
            return Decision(Action.ALERT, reason="block downgraded: analyst marked this host a false positive",
                            confidence=confidence, source_ip=src)
        if action == "BLOCK":
            return Decision(Action.BLOCK, reason=f"{self.policy} policy: block",
                            confidence=confidence, source_ip=src)
        if action == "INVESTIGATE":
            if self.actuator.is_blocked(src, now):  # simulate mode: real DROP would hide these
                return Decision(Action.NOOP, reason="source already blocked", confidence=confidence)
            return Decision(Action.INVESTIGATE, reason=f"{self.policy} policy: source handed to investigator",
                            confidence=confidence, source_ip=src)
        if action == "ALERT":
            return Decision(Action.ALERT, reason=f"{self.policy} policy: alert",
                            confidence=confidence, source_ip=src)

        can_retrain = now - self._last_retrain > self.retrain_cooldown
        if can_retrain and self.drift_monitor.is_drifting():
            return Decision(
                Action.RETRAIN,
                reason="rolling confidence below floor -- traffic no "
                       "longer matches learned patterns",
            )
        if can_retrain and now - self._last_self_eval > self.self_eval_interval:
            self._last_self_eval = now
            if self.self_eval_trigger.should_retrain(
                self.model, self.trainer.local_buffer, self.trainer.device
            ):
                return Decision(Action.RETRAIN, reason="model wrong on known local labeled data")
        return Decision(Action.NOOP, reason="nothing actionable", confidence=confidence)

    def act(self, decision: Decision, flow_record=None, now=None):
        """Execute the chosen action via the relevant tool, then reflect."""
        now = time.time() if now is None else now
        if decision.action == Action.BLOCK:
            head_start = 1 if decision.source_ip in self.peer_flagged else 0
            self.actuator.block(decision.source_ip, now, head_start=head_start)
            explanation = self._explain(flow_record)
            self.actuator.log_incident(self.device_id, decision, explanation=explanation)
            if self.policy == "bandit" and self.investigator:
                # block now, verify after: the verdict labels this BLOCK for
                # the bandit and rolls it back if the source was benign
                self._last_submitted = self.investigator.submit(
                    decision.source_ip, flow_record, self._last_p_attack, explanation, now)

        elif decision.action == Action.ALERT:
            self.actuator.log_incident(
                self.device_id, decision, explanation=self._explain(flow_record)
            )

        elif decision.action == Action.INVESTIGATE:
            explanation = self._explain(flow_record)
            self._last_submitted = self.investigator.submit(
                decision.source_ip, flow_record, self._last_p_attack, explanation, now)
            if self._last_submitted:
                self.actuator.log_incident(self.device_id, decision, explanation=explanation)

        elif decision.action == Action.RETRAIN:
            self._last_retrain = now
            self.drift_monitor.window.clear()  # judge the NEW model on fresh traffic
            new_adapter = self.trainer.local_retrain(self.model)
            self.model.load_adapter_state_dict(new_adapter)
            self.comms.upload_adapter(
                self.device_id, new_adapter, n_samples=self.trainer.last_batch_size,
                local_val_accuracy=self.trainer.last_val_accuracy,
            )
            self.actuator.log_incident(self.device_id, decision)

        self.reflect(decision)

    def sync(self, now):
        """Periodic, independent of what the current flow is -- it used to be
        a 'decision' reachable only on benign flows, so a device under
        sustained attack never pulled a new global model."""
        self._last_sync_check = now
        if self.share_intel:
            # replace, not union: a peer's ROLLBACK retracts its earlier BLOCK
            self.peer_flagged = self.comms.fetch_peer_blocks()
            # Federation acts, it doesn't just annotate: an IP a peer device
            # blocked is dropped here too, before it ever sends this device a
            # packet. This is the "device-2 blocks on first contact" moment --
            # device-2 never classified the attack, it inherited the verdict.
            # Guarded by is_blocked (log once per TTL) and by analyst
            # exceptions; a peer ROLLBACK removes the IP from peer_flagged so
            # it is not re-blocked. head_start=1: a peer-confirmed IP starts
            # one escalation level up.
            for ip in self.peer_flagged:
                if self.intel_scope is not None:
                    try:
                        if ipaddress.ip_address(ip) not in self.intel_scope:
                            continue
                    except ValueError:
                        continue
                if not self.actuator.is_blocked(ip, now) and self.exceptions.get(ip, float("-inf")) <= now:
                    self.actuator.block(ip, now, head_start=1)
                    self.actuator.log_incident(self.device_id, Decision(
                        Action.BLOCK, reason="pre-emptive block from peer threat intel",
                        source_ip=ip))
        global_adapter = self.comms.fetch_global_adapter()
        if global_adapter is None:
            return
        if not self.gate_updates:
            self.model.load_adapter_state_dict(global_adapter)
            self.reflect(Decision(Action.SYNC_DOWNLOAD, reason="global model adopted (ungated)"))
            return
        accepted, before, after = gated_load(self.model, global_adapter, self.trainer.val_buffer)
        detail = (f"local held-out acc {before[0]:.4f}->{after[0]:.4f}, "
                  f"FPR {before[1]:.4f}->{after[1]:.4f}")
        decision = Decision(Action.SYNC_DOWNLOAD if accepted else Action.REJECT_GLOBAL,
                            reason=("global model adopted: " if accepted else
                                    "global model REJECTED, kept local: ") + detail)
        self.actuator.log_incident(self.device_id, decision)
        self.reflect(decision)

    def tick(self, now=None):
        """Traffic-independent housekeeping, called every second from its own
        thread. In live-capture mode run_step only runs when a packet
        arrives, so a quiet node used to never expire blocks, never sync and
        never contribute to a round."""
        now = time.time() if now is None else now
        with self.lock:
            self.actuator.expire(now)
            if now - self._last_sync_check > self.sync_poll_interval:
                self.sync(now)
        if self.fed_interval:
            slot = int(now // self.fed_interval)
            if slot != self._fed_slot:
                self._fed_slot = slot
                self.contribute(now)

    def contribute(self, now):
        """One FedAvg client step: train a copy of the current model on this
        device's private labeled data and upload only the adapter weights.
        Training runs on a copy outside the lock so detection never stalls;
        the live detector only changes when the aggregated global model
        comes back and passes the local gate in sync()."""
        with self.lock:
            snapshot = copy.deepcopy(self.model)
        adapter = self.trainer.local_retrain(snapshot)
        acc = self.trainer.last_val_accuracy
        resp = self.comms.upload_adapter(
            self.device_id, adapter, n_samples=self.trainer.last_batch_size,
            local_val_accuracy=acc,
        )
        if resp:
            reason = (f"trained on {self.trainer.last_batch_size} private local rows "
                      f"(local val acc {acc:.4f}), adapter sent to round {resp.get('round')}")
        else:
            reason = "local training done, upload failed (kept locally)"
        decision = Decision(Action.FL_UPLOAD, reason=reason)
        with self.lock:
            self.actuator.log_incident(self.device_id, decision)
            self.reflect(decision)

    def feedback(self, source_ip, action, was_false_positive, now=None):
        """Analyst verdict on an earlier BLOCK/ALERT: roll back a wrong block
        and make that action more (or less) expensive from now on."""
        if was_false_positive and action == "BLOCK":
            self.actuator.rollback(source_ip)
            self.peer_flagged.discard(source_ip)
            self.exceptions[source_ip] = (time.time() if now is None else now) + self.exception_ttl
            # shared like a BLOCK, so peers drop this IP from their intel too
            self.actuator.log_incident(self.device_id, Decision(
                Action.ROLLBACK, reason="analyst: false positive", source_ip=source_ip))
        self.costs = update_costs(self.costs, action, was_false_positive)
        self.learn_from_label(source_ip, is_attack=not was_false_positive)

    def learn_from_label(self, ip, is_attack):
        """Reward every pending bandit decision on this source now that its
        label is known. Reward = -cost/20, same cost table as the offline
        experiment (cloud/bandit_experiment.py)."""
        if self.bandit is None:
            return
        for x, chosen, llm_call in self.pending.pop(ip, ()):
            cost = action_cost(chosen, is_attack, verdict_attack=is_attack)
            if chosen == "INVESTIGATE" and not llm_call:
                cost -= INVESTIGATE_COST  # covered by an earlier verdict on this source
            self.bandit.update(x, chosen, -cost / 20)

    def threat_intel(self, ip):
        """get_threat_intel tool for the investigator (read-only)."""
        return {"blocked_by_peer_device": ip in self.peer_flagged,
                "own_block_level": self.actuator.level.get(ip, 0),
                "analyst_false_positive_exception": self.exceptions.get(ip, 0) > time.time()}

    def apply_verdict(self, v, now):
        """Act on a finished investigation, on the agent's own thread."""
        ip = v["ip"]
        reason = f"investigator ({v['attack_type']}, conf {v['confidence']:.2f}): {v['rationale']}"
        action = {"block": Action.BLOCK, "alert": Action.ALERT,
                  "escalate": Action.ESCALATE}.get(v["action"], Action.NOOP)
        decision = Decision(action, reason=reason, confidence=v["confidence"], source_ip=ip)
        if action == Action.BLOCK and self.exceptions.get(ip, float("-inf")) > now:
            decision = Decision(Action.ALERT, reason="block downgraded (analyst exception): " + reason,
                                confidence=v["confidence"], source_ip=ip)
        if decision.action == Action.BLOCK:
            self.actuator.block(ip, now, head_start=1 if ip in self.peer_flagged else 0)
        # the verdict doubles as a WEAK label for the bandit (no ground truth
        # live); an escalation or an "unknown" type teaches it nothing
        if v["action"] != "escalate" and v["attack_type"] != "unknown":
            self.learn_from_label(ip, is_attack=v["attack_type"] != "benign")
        if v["action"] == "allow" and ip in self.actuator.blocked:
            self.actuator.rollback(ip)  # verify-after-block said benign
            # same learned exception an analyst false-positive gives: further
            # BLOCKs on this source are downgraded to ALERT until it expires
            self.exceptions[ip] = now + self.exception_ttl
            self.actuator.log_incident(self.device_id, Decision(
                Action.ROLLBACK, reason="investigator found the blocked source benign: " + reason,
                source_ip=ip))
        if decision.action != Action.NOOP or v["action"] == "allow":
            entry_decision = decision if decision.action != Action.NOOP else Decision(
                Action.NOOP, reason="investigator allowed: " + reason, source_ip=ip)
            self.actuator.log_incident(self.device_id, entry_decision,
                                       explanation={"investigation_trace": v["trace"],
                                                    "latency_s": v.get("latency_s")})
        self.reflect(decision)

    def _explain(self, flow_record):
        """Best-effort attention-rollout explanation for one flow --
        explainability is a nice-to-have, never let it break the actual
        detection/block path if the model wrapper isn't what's expected
        (e.g. in a unit test with a bare mock model)."""
        if flow_record is None:
            return None
        try:
            x_cont, x_cat = self.model.encoder.encode_row(flow_record)
            return attention_rollout(self.model.model, x_cont.unsqueeze(0), x_cat.unsqueeze(0))
        except AttributeError:
            return None

    def reflect(self, decision: Decision):
        """Record the decision + rationale -- feeds the explainability
        dashboard's decision trace, not just the model's attention weights."""
        self.log.append({
            "t": time.time(),
            "device": self.device_id,
            "action": decision.action.name,
            "reason": decision.reason,
            "confidence": decision.confidence,
        })

    def run_step(self, flow_record, now=None):
        """Returns (decision, pred_class, confidence) -- the caller (only
        run_edge_node.py today) needs the raw perception too, separate from
        the Decision the agent acted on, to detect a live-demo "miss": a
        known hold-out-attack replay row where the agent's own decision
        wasn't BLOCK/ALERT. That check belongs in the demo harness, not
        here -- the agent itself never sees ground-truth labels, only the
        harness (which controls the replay CSV) does."""
        now = time.time() if now is None else now
        with self.lock:
            return self._run_step(flow_record, now)

    def _run_step(self, flow_record, now):
        self.actuator.expire(now)
        if now - self._last_sync_check > self.sync_poll_interval:
            self.sync(now)
        if self.investigator:
            for v in self.investigator.verdicts():
                self.apply_verdict(v, now)
        pred_class, confidence, p_attack = self.perceive(flow_record)
        self._last_p_attack = p_attack
        decision = self.decide(p_attack, confidence, flow_record, now)
        if self.history:  # before act(), so the triggering flow is in the evidence
            self.history.add(flow_record, p_attack, decision.action.name, now)
        self._last_submitted = False
        self.act(decision, flow_record, now)
        src = getattr(flow_record, "src_ip", None)
        if self.bandit is not None and src and self._last_choice is not None:
            self.pending.setdefault(src, deque(maxlen=200)).append(
                (self._last_ctx, self._last_choice, self._last_submitted))
            if self.exceptions.get(src, float("-inf")) > now:
                # this source was already judged benign (analyst or verified
                # rollback): that label applies to this decision too
                self.learn_from_label(src, is_attack=False)
        return decision, pred_class, confidence
