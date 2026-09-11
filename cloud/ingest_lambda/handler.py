"""
cloud/ingest_lambda/handler.py

POST /update -- a device uploads its locally-retrained LoRA adapter.
Saves it to S3, joins it to the current round in DynamoDB, and -- if that
submission completes the round (all expected devices in) -- runs FedAvg
inline rather than invoking a separate Lambda. Simpler than a cross-Lambda
invoke for math that takes milliseconds; the EventBridge-scheduled
aggregate_lambda only exists for the straggler/timeout path, not this
happy-path completion (see memory.md §6).
"""
import json

from shared import store
from shared.aggregate import try_aggregate_round


def handler(event, context):
    body = json.loads(event["body"])
    device_id = body["device_id"]
    n_samples = int(body["n_samples"])
    weights = body["weights"]
    # Each device's own locally-reported validation accuracy (see
    # edge_agent/trainer.py's docstring) -- the cloud never runs the model
    # itself, so this is the only accuracy signal that exists anywhere.
    local_val_accuracy = float(body.get("local_val_accuracy", 0.0))

    updated = None
    round_number = None
    # One retry: if the round advances (another device's submission
    # completed it) between reading round state and joining it, re-fetch
    # and try again against the new round rather than erroring.
    for _ in range(2):
        state = store.get_round_state()
        round_number = state["round"]
        store.put_update_weights(
            round_number, device_id,
            {
                "device_id": device_id, "n_samples": n_samples, "weights": weights,
                "local_val_accuracy": local_val_accuracy,
            },
        )
        updated = store.try_join_round(device_id, round_number)
        if updated is not None:
            break
    else:
        return {
            "statusCode": 409,
            "body": json.dumps({"error": "round contention, retry the upload"}),
        }

    submitted = updated.get("submitted", set())
    aggregated = False
    if len(submitted) >= store.EXPECTED_DEVICES:
        aggregated = try_aggregate_round(round_number)

    return {
        "statusCode": 200,
        "body": json.dumps({
            "status": "accepted", "round": round_number, "aggregated": aggregated,
        }),
    }
