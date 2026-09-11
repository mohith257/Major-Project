"""
cloud/local_simulation.py

Proves the actual federated PROCESS works -- not just its ingredients in
isolation. Every earlier test in this project ran one device, one script,
sequentially. This runs 4 genuinely independent device models against the
REAL cloud/shared/store.py, aggregate.py, and all 6 Lambda handler
functions -- imported and called directly, not reimplemented -- backed by
moto-mocked DynamoDB + S3 (genuine conditional-expression semantics,
genuine S3 object storage, no real AWS billing or credentials needed).

What this validates that nothing before it did:
- multiple independent devices' updates actually completing a round and
  triggering real inline aggregation inside ingest_lambda
- the DynamoDB optimistic lock (try_lock_for_aggregation)
- the straggler/timeout path in aggregate_lambda
- devices pulling the aggregated result back down via model_lambda and
  successfully loading it into a fresh model instance
- the incident write/read round trip through incident_lambda /
  incidents_read_lambda, including attention-rollout data surviving
  DynamoDB's nested-map storage
- multiple ROUNDS in sequence, and what the GLOBAL (all-4-devices-
  averaged) model actually does on Fuzzers detection -- not just what
  Device 1's solo local model does

What this deliberately does NOT validate (still needs real AWS,
tomorrow): the actual API Gateway HTTP layer -- request routing, API key
auth enforcement, CORS, the exact Lambda proxy-integration event shape
API Gateway itself constructs. Handler functions are called directly with
hand-built event dicts containing only the fields the handlers actually
read (event["body"], event["queryStringParameters"]) -- that's everything
downstream of API Gateway, not API Gateway itself.

Run: python -m cloud.local_simulation
"""
import json
import os
import sys
import time

os.environ.setdefault("ROUND_STATE_TABLE", "fedgrid-round-state")
os.environ.setdefault("ROUNDS_TABLE", "fedgrid-rounds")
os.environ.setdefault("INCIDENTS_TABLE", "fedgrid-incidents")
os.environ.setdefault("WEIGHTS_BUCKET", "fedgrid-weights-sim")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("EXPECTED_DEVICES", "4")
os.environ.setdefault("ROUND_TIMEOUT_SECONDS", "30")

import boto3  # noqa: E402
import pandas as pd  # noqa: E402
import torch  # noqa: E402
from moto import mock_aws  # noqa: E402

from edge_agent.comms import _flatten_state, _unflatten_state  # noqa: E402
from edge_agent.inference import InferenceModel, SchemaEncoder  # noqa: E402
from edge_agent.trainer import LocalTrainer  # noqa: E402
from model.tabular_transformer import TabularTransformer  # noqa: E402

DEVICE_IDS = ["device1", "device2", "device3", "device4"]


def _provision_aws_resources():
    """Create the same tables/bucket template.yaml would create."""
    ddb = boto3.resource("dynamodb")
    ddb.create_table(
        TableName=os.environ["ROUND_STATE_TABLE"],
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    ddb.create_table(
        TableName=os.environ["ROUNDS_TABLE"],
        KeySchema=[{"AttributeName": "round", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "round", "AttributeType": "N"}],
        BillingMode="PAY_PER_REQUEST",
    )
    ddb.create_table(
        TableName=os.environ["INCIDENTS_TABLE"],
        KeySchema=[
            {"AttributeName": "device_id", "KeyType": "HASH"},
            {"AttributeName": "timestamp", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "device_id", "AttributeType": "S"},
            {"AttributeName": "timestamp", "AttributeType": "N"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    boto3.client("s3").create_bucket(Bucket=os.environ["WEIGHTS_BUCKET"])


def _load_backbone():
    ckpt = torch.load("model/backbone_frozen.pt", weights_only=False)
    model = TabularTransformer(
        n_continuous=ckpt["n_continuous"], cat_cardinalities=ckpt["cat_cardinalities"]
    )
    model.load_state_dict(ckpt["model_state_dict"])
    return model


def _load_device_buffer(device_id, encoder):
    df = pd.read_csv(f"data/processed/{device_id}_train.csv")
    return [(*encoder.encode_row(row), int(row["label"])) for _, row in df.iterrows()]


def main():
    with mock_aws():
        _provision_aws_resources()

        # Imported AFTER entering the mock context and provisioning, so
        # the module-level boto3 clients these bind at import time attach
        # to moto's backend, not real AWS. Short-form imports -- this is
        # exactly what runs inside the deployed Lambda zip, see
        # cloud/shared/serialization.py's docstring for why the import
        # convention differs from the rest of the repo.
        sys.path.insert(0, "cloud")
        import ingest_lambda.handler as ingest_h
        import model_lambda.handler as model_h
        import incident_lambda.handler as incident_write_h
        import incidents_read_lambda.handler as incident_read_h
        import aggregate_lambda.handler as straggler_h
        from shared import store

        encoder = SchemaEncoder("data/processed/vocab.json", "data/processed/scaler.json")
        backbone = _load_backbone()

        print("Loading each device's own local buffer (independent data, never shared)...")
        devices = {}
        for did in DEVICE_IDS:
            model = TabularTransformer(
                n_continuous=backbone.cont_proj.in_features,
                cat_cardinalities=[len(encoder.vocab[c]) for c in ["proto", "service", "state"]],
            )
            model.load_state_dict(backbone.state_dict())  # each starts identical, then diverges
            inf_model = InferenceModel(model, encoder)
            buffer = _load_device_buffer(did, encoder)
            trainer = LocalTrainer(buffer, epochs=5)
            devices[did] = {"model": inf_model, "trainer": trainer}
            print(f"  {did}: {len(buffer)} local rows")

        # ---- shared evaluation data (never touched by any device's training) ----
        replay_df = pd.read_csv("data/processed/holdout_replay.csv")

        def eval_fuzzers(inf_model):
            correct = 0
            for _, row in replay_df.iterrows():
                pred = inf_model.infer(row).argmax(dim=-1).item()
                correct += int(pred == row["label"])
            return correct / len(replay_df)

        print(f"\nFuzzers replay accuracy BEFORE any round: "
              f"{eval_fuzzers(devices['device1']['model']):.4f} (all devices start identical)")

        # ---- ROUND 1: all 4 devices retrain locally and upload via the REAL ingest Lambda ----
        print("\n=== ROUND 1: all 4 devices retrain + upload ===")
        for did in DEVICE_IDS:
            d = devices[did]
            t0 = time.time()
            new_adapter = d["trainer"].local_retrain(d["model"])
            d["model"].load_adapter_state_dict(new_adapter)
            from shared.serialization import encode_state
            event = {
                "body": json.dumps({
                    "device_id": did,
                    "n_samples": d["trainer"].last_batch_size,
                    "local_val_accuracy": d["trainer"].last_val_accuracy,
                    "weights": encode_state(_flatten_state(new_adapter)),
                })
            }
            result = ingest_h.handler(event, None)
            body = json.loads(result["body"])
            print(f"  {did}: retrain {time.time()-t0:.1f}s -> ingest_lambda round={body['round']} "
                  f"aggregated={body['aggregated']} (statusCode={result['statusCode']})")

        state_after_r1 = store.get_round_state()
        print(f"round_state after round 1: round={state_after_r1['round']} "
              f"latest_global_round={state_after_r1['latest_global_round']}")
        assert state_after_r1["latest_global_round"] == 1, "round 1 should have auto-aggregated"

        # ---- all 4 devices pull the aggregated global model back down ----
        print("\nAll 4 devices fetching the aggregated global model via model_lambda...")
        from shared.serialization import decode_state
        for did in DEVICE_IDS:
            event = {"queryStringParameters": {"since_round": "0"}}
            result = model_h.handler(event, None)
            assert result["statusCode"] == 200, f"{did} should see a new global model"
            body = json.loads(result["body"])
            global_adapter = _unflatten_state(decode_state(body["weights"]))
            devices[did]["model"].load_adapter_state_dict(global_adapter)
        print(f"  all 4 devices now running the round-{body['round']} GLOBAL model "
              f"(averaged across all 4 devices' updates)")

        global_fuzzers_acc = eval_fuzzers(devices["device2"]["model"])  # device2 never saw Fuzzers
        print(f"\nFuzzers replay accuracy on the GLOBAL model, measured on device2 "
              f"(never saw Fuzzers data itself): {global_fuzzers_acc:.4f}")

        # ---- ROUND 2: do it again, confirm the round counter and coordination keep working ----
        print("\n=== ROUND 2: all 4 devices retrain + upload again ===")
        for did in DEVICE_IDS:
            d = devices[did]
            new_adapter = d["trainer"].local_retrain(d["model"])
            d["model"].load_adapter_state_dict(new_adapter)
            event = {
                "body": json.dumps({
                    "device_id": did,
                    "n_samples": d["trainer"].last_batch_size,
                    "local_val_accuracy": d["trainer"].last_val_accuracy,
                    "weights": encode_state(_flatten_state(new_adapter)),
                })
            }
            result = ingest_h.handler(event, None)
            body = json.loads(result["body"])
            print(f"  {did}: round={body['round']} aggregated={body['aggregated']}")

        state_after_r2 = store.get_round_state()
        assert state_after_r2["latest_global_round"] == 2, "round 2 should have auto-aggregated"
        for did in DEVICE_IDS:
            event = {"queryStringParameters": {"since_round": "1"}}
            result = model_h.handler(event, None)
            body = json.loads(result["body"])
            global_adapter = _unflatten_state(decode_state(body["weights"]))
            devices[did]["model"].load_adapter_state_dict(global_adapter)
        global_fuzzers_acc_r2 = eval_fuzzers(devices["device2"]["model"])
        print(f"Fuzzers replay accuracy on the round-2 GLOBAL model (device2): "
              f"{global_fuzzers_acc_r2:.4f}")

        # ---- STRAGGLER TEST: only 2 of 4 report, timeout forces aggregation anyway ----
        print("\n=== ROUND 3: straggler test (only device1 + device3 report) ===")
        for did in ["device1", "device3"]:
            d = devices[did]
            new_adapter = d["trainer"].local_retrain(d["model"])
            event = {
                "body": json.dumps({
                    "device_id": did,
                    "n_samples": d["trainer"].last_batch_size,
                    "local_val_accuracy": d["trainer"].last_val_accuracy,
                    "weights": encode_state(_flatten_state(new_adapter)),
                })
            }
            result = ingest_h.handler(event, None)
            body = json.loads(result["body"])
            print(f"  {did}: round={body['round']} aggregated={body['aggregated']} "
                  f"(expected False -- only 2 of 4 in)")

        # simulate the round timeout having elapsed (moto's clock is real
        # wall-clock, so back-date round_started_at rather than sleep 30s)
        table = boto3.resource("dynamodb").Table(os.environ["ROUND_STATE_TABLE"])
        table.update_item(
            Key={"pk": "GLOBAL"},
            UpdateExpression="SET round_started_at = :t",
            ExpressionAttributeValues={":t": int(time.time()) - 999},
        )
        straggler_result = straggler_h.handler({}, None)
        print(f"  straggler handler result: {straggler_result}")
        state_after_r3 = store.get_round_state()
        assert state_after_r3["latest_global_round"] == 3, "straggler path should have aggregated round 3"
        print(f"  round 3 aggregated with only 2/4 devices -- straggler handling confirmed working")

        # ---- INCIDENT ROUND TRIP: write via incident_lambda, read via incidents_read_lambda ----
        print("\n=== Incident write/read round trip ===")
        incident_entry = {
            "device_id": "device1", "action": "BLOCK", "reason": "high-confidence malicious flow",
            "confidence": 0.94, "source_ip": "10.12.9.201",
            "attention": {"continuous_features": 0.4, "proto": 0.2, "service": 0.2, "state": 0.2},
        }
        write_result = incident_write_h.handler({"body": json.dumps(incident_entry)}, None)
        print(f"  incident_lambda (write): statusCode={write_result['statusCode']}")
        read_result = incident_read_h.handler({"queryStringParameters": {"limit": "10"}}, None)
        incidents = json.loads(read_result["body"])["incidents"]
        print(f"  incidents_read_lambda (read): {len(incidents)} incident(s) found")
        assert len(incidents) == 1
        assert incidents[0]["attention"]["proto"] == 0.2, "attention data must survive the round trip"
        print("  attention-rollout data survived the DynamoDB round trip intact")

        print("\n=== SUMMARY ===")
        print(f"Fuzzers replay BEFORE any round: (see above)")
        print(f"Fuzzers replay AFTER round 1 (global, avg of all 4 devices): {global_fuzzers_acc:.4f}")
        print(f"Fuzzers replay AFTER round 2 (global, avg of all 4 devices): {global_fuzzers_acc_r2:.4f}")
        print(f"3 rounds completed, straggler path confirmed, incident round trip confirmed")


if __name__ == "__main__":
    main()
