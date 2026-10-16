"""
cloud/shared/aggregate.py

The FedAvg math + the "is it actually safe/my job to aggregate right now"
decision -- shared by ingest_lambda (the happy-path quorum trigger) and
aggregate_lambda (the EventBridge-scheduled straggler/timeout trigger), so
one place decides what an aggregation IS and the two trigger paths can't
disagree about it.

Uses short-form imports (`from shared import ...`) because this module is
only ever loaded inside the Lambda zip context, where the packaged cloud/
directory IS the import root -- see serialization.py's docstring.
"""
from shared import store
from shared.serialization import decode_state, encode_state, weighted_average


def try_aggregate_round(round_number: int):
    """Safe to call speculatively from either trigger path -- the lock in
    try_lock_for_aggregation means at most one caller actually does the
    work, even if both fire at nearly the same moment. Returns True if
    this invocation performed the aggregation."""
    if not store.try_lock_for_aggregation(round_number):
        return False
    try:
        return _aggregate_locked(round_number)
    except Exception:
        store.release_aggregation_lock(round_number)
        raise


def _aggregate_locked(round_number):
    submissions = store.list_update_weights(round_number)
    # Drop submissions whose tensor names don't match the majority -- one
    # device still running an old adapter format (as happened 2026-10 with
    # global/round10892.json) used to KeyError inside weighted_average.
    key_sets = [frozenset(s["weights"]) for s in submissions]
    if key_sets:
        majority = max(set(key_sets), key=key_sets.count)
        submissions = [s for s, k in zip(submissions, key_sets) if k == majority]
    if not submissions:
        store.release_aggregation_lock(round_number)
        return False

    states_with_weights = [
        (decode_state(s["weights"]), s["n_samples"]) for s in submissions
    ]
    new_global = weighted_average(states_with_weights)

    # Sample-weighted average of each contributing device's own locally-
    # reported validation accuracy -- NOT an independent global-test-set
    # evaluation (the cloud never runs the model, see serialization.py's
    # docstring). Same formula as the weight averaging itself, just on a
    # scalar per device instead of a tensor.
    total_n = sum(s["n_samples"] for s in submissions)
    avg_val_accuracy = sum(
        s.get("local_val_accuracy", 0.0) * s["n_samples"] for s in submissions
    ) / total_n if total_n else 0.0

    store.put_global_weights(round_number, encode_state(new_global))
    store.complete_round(
        round_number,
        participants=[s["device_id"] for s in submissions],
        avg_val_accuracy=avg_val_accuracy,
    )
    return True
