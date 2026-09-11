"""
cloud/rounds_lambda/handler.py

GET /rounds -- round-by-round history for the dashboard's accuracy chart
and per-round contribution view. Read-only, no coordination logic here
(that all lives in shared/store.py + shared/aggregate.py).
"""
import json

from shared import store


def handler(event, context):
    params = event.get("queryStringParameters") or {}
    limit = int(params.get("limit", 50))
    rounds = store.list_rounds(limit=limit)
    return {"statusCode": 200, "body": json.dumps({"rounds": rounds})}
