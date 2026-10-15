"""
cloud/shared/store.py

Thin boto3 wrappers shared by all 4 Lambda functions -- DynamoDB round
coordination + S3 weight storage. A Lambda invocation remembers nothing
from any previous one (that's the whole reason round coordination needs a
database at all -- see memory.md §6), so every function reads/writes
through here rather than holding anything in module state.

All DynamoDB expressions alias "round" and "status" via
ExpressionAttributeNames unconditionally -- both are plausible reserved
words, and a literal reserved word in an expression fails with a
confusing ValidationException, so alias rather than gamble on the exact
reserved-word list.

Imported only from inside the Lambda zip context as `shared.store` (see
serialization.py's docstring for why the two import conventions differ).
"""
import json
import os
import time
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError


def _to_native(obj):
    """boto3's DynamoDB resource API returns every Number attribute as a
    Decimal, not int/float -- caught the hard way: json.dumps() can't
    serialize Decimal, so the very first Lambda response in the local
    federated simulation (cloud/local_simulation.py) crashed on this
    before it ever touched real AWS. This is standard DynamoDB/boto3
    behavior, not a moto quirk -- would have broken the real deployment
    too. Converts recursively so nothing outside this module ever has to
    know DynamoDB exists."""
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_native(v) for v in obj]
    if isinstance(obj, set):
        return {_to_native(v) for v in obj}
    return obj


def _to_dynamo(obj):
    """The inverse, needed on the write side: boto3's resource API
    rejects native Python floats outright ('Float types are not
    supported. Use Decimal types instead.') -- so anything with a float
    in it (avg_val_accuracy, an incident's confidence, attention-rollout
    values) has to be converted before put_item/update_item."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_dynamo(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_dynamo(v) for v in obj]
    return obj


ROUND_STATE_TABLE = os.environ["ROUND_STATE_TABLE"]
ROUNDS_TABLE = os.environ["ROUNDS_TABLE"]
INCIDENTS_TABLE = os.environ["INCIDENTS_TABLE"]
BUCKET = os.environ["WEIGHTS_BUCKET"]
EXPECTED_DEVICES = int(os.environ.get("EXPECTED_DEVICES", "4"))
ROUND_TIMEOUT_SECONDS = int(os.environ.get("ROUND_TIMEOUT_SECONDS", "30"))

_dynamodb = boto3.resource("dynamodb")
_s3 = boto3.client("s3")

ROUND_STATE_KEY = {"pk": "GLOBAL"}


def get_round_state():
    table = _dynamodb.Table(ROUND_STATE_TABLE)
    resp = table.get_item(Key=ROUND_STATE_KEY)
    item = resp.get("Item")
    if item is None:
        # "submitted" is deliberately omitted here -- DynamoDB rejects an
        # empty String Set on PutItem; try_join_round's ADD creates the
        # attribute on first use, which IS valid.
        item = {
            "pk": "GLOBAL", "round": 1, "latest_global_round": 0,
            "status": "collecting", "round_started_at": int(time.time()),
        }
        table.put_item(Item=item)
    return _to_native(item)


def try_join_round(device_id: str, round_number: int):
    """Atomically add device_id to this round's submitted set (DynamoDB
    sets dedupe automatically, so a retried request can't double count).
    Returns the updated item's Attributes, or None if the round already
    advanced past round_number -- caller should re-fetch and retry."""
    table = _dynamodb.Table(ROUND_STATE_TABLE)
    try:
        resp = table.update_item(
            Key=ROUND_STATE_KEY,
            UpdateExpression="ADD submitted :d",
            ConditionExpression="#r = :r",
            ExpressionAttributeNames={"#r": "round"},
            ExpressionAttributeValues={":d": {device_id}, ":r": round_number},
            ReturnValues="ALL_NEW",
        )
        return _to_native(resp["Attributes"])
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return None
        raise


def try_lock_for_aggregation(round_number: int):
    """Optimistic lock: flips status collecting -> aggregating, only if
    it's still collecting for this exact round. Returns True if this
    invocation won the lock and should actually run FedAvg. Two
    near-simultaneous callers hitting quorum (or a straggler timeout
    landing right as quorum completes) will both attempt this; exactly one
    wins, the other gets a ConditionalCheckFailedException and backs off
    instead of racing on the aggregation math."""
    table = _dynamodb.Table(ROUND_STATE_TABLE)
    try:
        table.update_item(
            Key=ROUND_STATE_KEY,
            UpdateExpression="SET #s = :aggregating",
            ConditionExpression="#r = :r AND #s = :collecting",
            ExpressionAttributeNames={"#r": "round", "#s": "status"},
            ExpressionAttributeValues={
                ":aggregating": "aggregating",
                ":collecting": "collecting",
                ":r": round_number,
            },
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def complete_round(round_number: int, participants: list, avg_val_accuracy: float = 0.0):
    """Bump to the next round, reset submitted, record history. Called
    once, only by whichever invocation won try_lock_for_aggregation."""
    table = _dynamodb.Table(ROUND_STATE_TABLE)
    table.update_item(
        Key=ROUND_STATE_KEY,
        UpdateExpression=(
            "SET #r = :next_round, latest_global_round = :done, "
            "#s = :collecting, round_started_at = :now "
            "REMOVE submitted"
        ),
        ExpressionAttributeNames={"#r": "round", "#s": "status"},
        ExpressionAttributeValues={
            ":next_round": round_number + 1,
            ":done": round_number,
            ":collecting": "collecting",
            ":now": int(time.time()),
        },
    )
    _dynamodb.Table(ROUNDS_TABLE).put_item(Item=_to_dynamo({
        "round": round_number,
        "completed_at": int(time.time()),
        "participants": participants,
        # sample-weighted average of participants' own locally-reported
        # validation accuracy -- see the note in shared/aggregate.py.
        "avg_val_accuracy": avg_val_accuracy,
    }))


def _scan_all(table, cap=100000):
    """DynamoDB Scan's Limit caps how many items it EVALUATES, not how many
    survive a subsequent sort -- table.scan(Limit=N) then sorting just
    those N is wrong for "most recent N" and was caught for real
    (2026-09-21): with old and new data both in the table, it was
    returning an arbitrary early-scanned segment (stale week-old items)
    instead of the actual most recent ones. A first fix capped this
    helper's own full-table scan at 5000 items as a defensive limit -- but
    Scan traverses in partition order, not timestamp order, so with 24k+
    items dominated by one stale device's partition, THAT cap reproduced
    the exact same bug one level down (stopped scanning while still stuck
    in old data, never reaching today's rows). `cap` is now high enough to
    be a pure runaway-growth guard, not something a normal demo session
    will ever hit -- a real deployment would use a GSI on timestamp
    instead of scanning at all."""
    items = []
    resp = table.scan()
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp and len(items) < cap:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))
    return _to_native(items)


def list_rounds(limit: int = 50):
    """Most recent completed rounds first -- what the dashboard's accuracy
    chart and per-round contribution view are built from."""
    table = _dynamodb.Table(ROUNDS_TABLE)
    items = _scan_all(table)
    items.sort(key=lambda r: r["round"], reverse=True)
    return items[:limit]


def list_incidents(limit: int = 100):
    """Most recent incidents first, across all devices -- the dashboard's
    live incident feed."""
    table = _dynamodb.Table(INCIDENTS_TABLE)
    items = _scan_all(table)
    items.sort(key=lambda i: i.get("timestamp", 0), reverse=True)
    return items[:limit]


def put_update_weights(round_number: int, device_id: str, submission: dict):
    """submission: {"device_id":..., "n_samples":..., "weights": wire_state}"""
    _s3.put_object(
        Bucket=BUCKET,
        Key=f"updates/round{round_number}/{device_id}.json",
        Body=json.dumps(submission).encode("utf-8"),
    )


def list_update_weights(round_number: int):
    """Returns every submission saved for this round -- the pieces FedAvg
    averages together."""
    prefix = f"updates/round{round_number}/"
    resp = _s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
    out = []
    for obj in resp.get("Contents", []):
        body = _s3.get_object(Bucket=BUCKET, Key=obj["Key"])["Body"].read()
        out.append(json.loads(body))
    return out


def put_global_weights(round_number: int, wire_state: dict):
    _s3.put_object(
        Bucket=BUCKET,
        Key=f"global/round{round_number}.json",
        Body=json.dumps(wire_state).encode("utf-8"),
    )


def get_global_weights(round_number: int):
    body = _s3.get_object(
        Bucket=BUCKET, Key=f"global/round{round_number}.json"
    )["Body"].read()
    return json.loads(body)


def put_incident(entry: dict):
    entry = dict(entry)
    entry.setdefault("device_id", "unknown")
    entry.setdefault("timestamp", int(time.time() * 1000))
    _dynamodb.Table(INCIDENTS_TABLE).put_item(Item=_to_dynamo(entry))
