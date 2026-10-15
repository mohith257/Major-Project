"""
cloud/aggregate_lambda/handler.py

EventBridge-scheduled straggler handler (memory.md §6). Runs on a fixed
schedule (see template.yaml -- compressed for the live demo, a real
deployment would use a longer interval). If a round has been open longer
than ROUND_TIMEOUT_SECONDS with at least MIN_STRAGGLER_PARTICIPANTS of the
expected devices reported, force it to close with whoever's in -- mirrors
the client-dropout problem from Nishio & Yonetani (already in the lit
review).

MIN_STRAGGLER_PARTICIPANTS was originally 2 -- "averaging a single device
has no privacy-mixing benefit." Lowered to 1 (2026-09-21) after discovering
live (not assumed) that with the current, more-accurate post-§12 backbone,
devices 2-4's own-buffer accuracy is 96-99%, well above any reasonable
self-eval floor, and StreamDriftMonitor's confidence floor (0.6) is nowhere
close to reachable even under aggressive hold-out replay injection (real
measured average confidence stays ~0.91-0.95). So devices 2-4 have no
organic path to ever retrain with this backbone -- requiring >=2 organic
participants means the round provably never completes, not just slowly.
This is a genuine finding, not a workaround: this system's accuracy is
high enough that only the device holding the rare/held-out class has any
reason to update in a given round. Worth a paragraph in the
report/limitations section, not hidden.
"""
import time

from shared import store
from shared.aggregate import try_aggregate_round

MIN_STRAGGLER_PARTICIPANTS = 1


def handler(event, context):
    state = store.get_round_state()
    if state.get("status") != "collecting":
        return {"skipped": "not collecting"}

    elapsed = int(time.time()) - int(state["round_started_at"])
    submitted = state.get("submitted", set())

    if elapsed < store.ROUND_TIMEOUT_SECONDS:
        return {"skipped": "not timed out", "elapsed": elapsed}

    if len(submitted) < MIN_STRAGGLER_PARTICIPANTS:
        return {"skipped": "too few participants to aggregate", "n": len(submitted)}

    aggregated = try_aggregate_round(state["round"])
    return {
        "aggregated": aggregated,
        "round": state["round"],
        "participants": len(submitted),
    }
