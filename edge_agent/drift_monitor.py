"""
edge_agent/drift_monitor.py

Two independent triggers feed EdgeAgent.decide(). They are not
interchangeable -- see memory.md §8 for why the demo depends on one and not
the other.

1. StreamDriftMonitor -- watches the *unlabeled* live stream. If the
   classifier's own confidence degrades over a sliding window, that's a
   signal the incoming traffic no longer matches learned patterns. This is
   the interesting, citable, "genuinely autonomous" trigger -- but it's
   statistical, so don't depend on it firing at an exact moment live.

2. LocalSelfEvalTrigger -- periodically re-scores the device's own local
   labeled buffer (historical, analyst-reviewed data) against the current
   model. If accuracy drops below threshold, that's deterministic: "I have
   known-correct answers I'm getting wrong, retrain." Use this as the
   reliable trigger for anything that must fire predictably in a live demo.
"""
from collections import deque
import statistics

import torch


class StreamDriftMonitor:
    def __init__(self, window=50, confidence_floor=0.6, min_samples=20):
        self.window = deque(maxlen=window)
        self.confidence_floor = confidence_floor
        self.min_samples = min_samples

    def update(self, confidence: float):
        self.window.append(confidence)

    def is_drifting(self) -> bool:
        if len(self.window) < self.min_samples:
            return False
        return statistics.mean(self.window) < self.confidence_floor


class LocalSelfEvalTrigger:
    # 0.85 was calibrated against the pre-2026-09-14 backbone (the one with
    # the LoRA-base-never-trained bug, memory.md §12). After that fix,
    # general accuracy is high enough that device1's own-buffer accuracy is
    # 87.49% -- ABOVE the old floor -- so this "reliable" trigger silently
    # never fired again post-fix. Nobody caught it because every multiround
    # experiment (cloud/multiround_fuzzers_experiment.py) force-reveals
    # Fuzzers tranches directly rather than waiting on this trigger; this
    # was only discovered 2026-09-21 running the live EC2 demo for real,
    # where device1 ran 56 minutes / 73 steps without ever retraining.
    # Recalibrated against the CURRENT backbone's real measured per-device
    # numbers (device1 87.49%, devices 2-4 96-99%) -- 0.90 fires reliably
    # and only on device1, matching the original design intent. Re-check
    # this number any time the backbone is retrained.
    def __init__(self, accuracy_floor=0.90):
        self.accuracy_floor = accuracy_floor

    def should_retrain(self, model, local_buffer, device="cpu") -> bool:
        """local_buffer: list of (x_cont, x_cat, label) this device already
        has ground truth for. True if the current model is wrong often
        enough on its own known data to justify retraining. Batched (was a
        per-row Python loop -- for device1's 104,606-row buffer that took
        ~46s/call in production, the same class of bug already fixed once
        in model/evaluate.py's predict_all(), see memory.md §11b)."""
        if not local_buffer:
            return False
        model.eval()
        x_cont = torch.stack([b[0] for b in local_buffer]).to(device)
        x_cat = torch.stack([b[1] for b in local_buffer]).to(device)
        labels = torch.tensor([b[2] for b in local_buffer], device=device)
        correct = 0
        with torch.no_grad():
            for i in range(0, len(local_buffer), 2048):
                logits = model(x_cont[i:i + 2048], x_cat[i:i + 2048])
                preds = logits.argmax(dim=-1)
                correct += (preds == labels[i:i + 2048]).sum().item()
        accuracy = correct / len(local_buffer)
        return accuracy < self.accuracy_floor
