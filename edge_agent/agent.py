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

from model.explain import attention_rollout


class Action(Enum):
    NOOP = auto()
    ALERT = auto()
    BLOCK = auto()
    RETRAIN = auto()
    SYNC_DOWNLOAD = auto()


@dataclass
class Decision:
    action: Action
    reason: str
    confidence: float = None
    source_ip: str = None


class EdgeAgent:
    def __init__(self, device_id, model, drift_monitor, self_eval_trigger,
                 trainer, actuator, comms, block_confidence=0.9,
                 sync_poll_interval=15):
        self.device_id = device_id
        self.model = model
        self.drift_monitor = drift_monitor
        self.self_eval_trigger = self_eval_trigger
        self.trainer = trainer
        self.actuator = actuator
        self.comms = comms
        self.block_confidence = block_confidence
        self.sync_poll_interval = sync_poll_interval
        self._last_sync_check = 0.0
        self.log = []

    def perceive(self, flow_record):
        """Score one incoming (unlabeled) flow. Returns (pred_class, confidence)."""
        logits = self.model.infer(flow_record)
        probs = logits.softmax(dim=-1)
        confidence, pred_class = probs.max(dim=-1)
        confidence = confidence.item()
        pred_class = pred_class.item()
        self.drift_monitor.update(confidence)
        return pred_class, confidence

    def decide(self, pred_class, confidence, flow_record) -> Decision:
        """Pick exactly one action given current perception + local state."""
        if pred_class == 1 and confidence >= self.block_confidence:
            return Decision(
                Action.BLOCK, reason="high-confidence malicious flow",
                confidence=confidence, source_ip=flow_record.src_ip,
            )

        if pred_class == 1:
            return Decision(
                Action.ALERT, reason="malicious but below block threshold",
                confidence=confidence, source_ip=flow_record.src_ip,
            )

        if self.drift_monitor.is_drifting():
            return Decision(
                Action.RETRAIN,
                reason="rolling confidence below floor -- traffic no "
                       "longer matches learned patterns",
            )

        if self.self_eval_trigger.should_retrain(
            self.model, self.trainer.local_buffer, self.trainer.device
        ):
            return Decision(
                Action.RETRAIN, reason="model wrong on known local labeled data",
            )

        if time.time() - self._last_sync_check > self.sync_poll_interval:
            return Decision(Action.SYNC_DOWNLOAD, reason="periodic global-model check")

        return Decision(Action.NOOP, reason="nothing actionable")

    def act(self, decision: Decision, flow_record=None):
        """Execute the chosen action via the relevant tool, then reflect."""
        if decision.action == Action.BLOCK:
            self.actuator.block(decision.source_ip)
            self.actuator.log_incident(
                self.device_id, decision, explanation=self._explain(flow_record)
            )

        elif decision.action == Action.ALERT:
            self.actuator.log_incident(
                self.device_id, decision, explanation=self._explain(flow_record)
            )

        elif decision.action == Action.RETRAIN:
            new_adapter = self.trainer.local_retrain(self.model)
            self.model.load_adapter_state_dict(new_adapter)
            self.comms.upload_adapter(
                self.device_id, new_adapter, n_samples=self.trainer.last_batch_size,
                local_val_accuracy=self.trainer.last_val_accuracy,
            )
            self.actuator.log_incident(self.device_id, decision)

        elif decision.action == Action.SYNC_DOWNLOAD:
            self._last_sync_check = time.time()
            global_adapter = self.comms.fetch_global_adapter()
            if global_adapter is not None:
                self.model.load_adapter_state_dict(global_adapter)

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

    def run_step(self, flow_record):
        """Returns (decision, pred_class, confidence) -- the caller (only
        run_edge_node.py today) needs the raw perception too, separate from
        the Decision the agent acted on, to detect a live-demo "miss": a
        known hold-out-attack replay row where the agent's own decision
        wasn't BLOCK/ALERT. That check belongs in the demo harness, not
        here -- the agent itself never sees ground-truth labels, only the
        harness (which controls the replay CSV) does."""
        pred_class, confidence = self.perceive(flow_record)
        decision = self.decide(pred_class, confidence, flow_record)
        self.act(decision, flow_record)
        return decision, pred_class, confidence
