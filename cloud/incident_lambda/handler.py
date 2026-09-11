"""
cloud/incident_lambda/handler.py

POST /incidents -- a device's DefenseActuator logs a block/alert decision
here. Pure write-through to DynamoDB; the dashboard reads this table
directly, this Lambda doesn't do anything with the data itself.
"""
import json

from shared import store


def handler(event, context):
    entry = json.loads(event["body"])
    store.put_incident(entry)
    return {"statusCode": 200, "body": json.dumps({"status": "logged"})}
