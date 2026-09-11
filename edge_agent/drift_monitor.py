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
    def __init__(self, accuracy_floor=0.85):
        self.accuracy_floor = accuracy_floor

    def should_retrain(self, model, local_buffer, device="cpu") -> bool:
        """local_buffer: list of (x_cont, x_cat, label) this device already
        has ground truth for. True if the current model is wrong often
        enough on its own known data to justify retraining."""
        if not local_buffer:
            return False
        model.eval()
        correct = 0
        with torch.no_grad():
            for x_cont, x_cat, label in local_buffer:
                logits = model(
                    x_cont.unsqueeze(0).to(device), x_cat.unsqueeze(0).to(device)
                )
                pred = logits.argmax(dim=-1).item()
                correct += int(pred == label)
        accuracy = correct / len(local_buffer)
        return accuracy < self.accuracy_floor
