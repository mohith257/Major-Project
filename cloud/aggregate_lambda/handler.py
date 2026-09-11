"""
cloud/aggregate_lambda/handler.py

EventBridge-scheduled straggler handler (memory.md §6). Runs on a fixed
schedule (see template.yaml -- compressed for the live demo, a real
deployment would use a longer interval). If a round has been open longer
than ROUND_TIMEOUT_SECONDS with at least MIN_STRAGGLER_PARTICIPANTS of the
expected devices reported, force it to close with whoever's in -- mirrors
the client-dropout problem from Nishio & Yonetani (already in the lit
review). If nobody's reported yet, or only 1 has, leaves it open --
averaging a single device has no privacy-mixing benefit and there's
nothing useful to aggregate from it alone.
"""
import time

from shared import store
from shared.aggregate import try_aggregate_round

MIN_STRAGGLER_PARTICIPANTS = 2


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
