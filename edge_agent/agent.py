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
import time
from dataclasses import dataclass
from enum import Enum, auto

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
                 exception_ttl=1800):
        self.device_id = device_id
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
        action = (choose_action(p_attack, self.costs) if self.policy == "cost"
                  else threshold_action(p_attack, self.block_confidence))
        if action == "ALERT" and src in self.peer_flagged:
            return Decision(Action.BLOCK, reason="suspicious flow from an IP a peer device blocked",
                            confidence=confidence, source_ip=src)
        if action == "BLOCK" and self.exceptions.get(src, float("-inf")) > now:
            return Decision(Action.ALERT, reason="block downgraded: analyst marked this host a false positive",
                            confidence=confidence, source_ip=src)
        if action == "BLOCK":
            return Decision(Action.BLOCK, reason=f"{self.policy} policy: block",
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
            self.actuator.log_incident(
                self.device_id, decision, explanation=self._explain(flow_record)
            )

        elif decision.action == Action.ALERT:
            self.actuator.log_incident(
                self.device_id, decision, explanation=self._explain(flow_record)
            )

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
        if not accepted:
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
        self.actuator.expire(now)
        if now - self._last_sync_check > self.sync_poll_interval:
            self.sync(now)
        pred_class, confidence, p_attack = self.perceive(flow_record)
        decision = self.decide(p_attack, confidence, flow_record, now)
        self.act(decision, flow_record, now)
        return decision, pred_class, confidence
