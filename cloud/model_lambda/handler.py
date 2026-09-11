"""
cloud/model_lambda/handler.py

GET /model?since_round=N -- a device checks whether a newer global model
exists than the one it already has. 204 (no body) if not; otherwise the
latest aggregated adapter weights. Round 0 (the initial frozen backbone's
baked-in adapter state) is never served from here -- every device already
has it locally from model/backbone_frozen.pt at boot, so this only ever
needs to hand out round 1+.
"""
import json

from shared import store


def handler(event, context):
    params = event.get("queryStringParameters") or {}
    since_round = int(params.get("since_round", 0))

    state = store.get_round_state()
    latest = state.get("latest_global_round", 0)

    if latest <= since_round:
        return {"statusCode": 204, "body": ""}

    weights = store.get_global_weights(latest)
    return {
        "statusCode": 200,
        "body": json.dumps({"round": latest, "weights": weights}),
    }
