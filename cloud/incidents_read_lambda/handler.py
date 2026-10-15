"""
cloud/incidents_read_lambda/handler.py

GET /incidents -- the dashboard's live incident feed. Separate Lambda from
incident_lambda (which handles POST /incidents, the write side a device's
DefenseActuator calls) -- same API Gateway path, different HTTP method,
different function, kept as two single-responsibility handlers rather than
one function branching on event["httpMethod"].
"""
import json

from shared import store


def handler(event, context):
    params = event.get("queryStringParameters") or {}
    limit = int(params.get("limit", 100))
    incidents = store.list_incidents(limit=limit)
    return {
        "statusCode": 200,
        "headers": {"Access-Control-Allow-Origin": "*"},
        "body": json.dumps({"incidents": incidents}),
    }
