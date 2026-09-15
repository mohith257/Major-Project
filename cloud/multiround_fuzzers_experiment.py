"""
cloud/multiround_fuzzers_experiment.py

Multi-round progressive Fuzzers-recovery experiment -- agreed in
memory.md §11e but not run until now. Every prior Fuzzers-recovery number
(memory.md §11b/§11d) came from Device 1 getting its ENTIRE static
12,729-row Fuzzers slice in one local retrain, then federating once or
twice. This experiment instead reveals that same 12,729-row pool to
Device 1 PROGRESSIVELY across rounds (25% / 50% / 75% / 100% cumulative)
to simulate a device that encounters more of the hold-out attack over
time, rather than having it all on day one, and tracks how the GLOBAL
(FedAvg-averaged) model's Fuzzers recall evolves round over round.

Does NOT touch data/processed/holdout_replay.csv or the official
data/raw/unsw_nb15_test.csv Fuzzers rows for training -- both stay
exactly as reserved for evaluation (memory.md §11e's explicit
constraint). The progressive tranches are carved out of Device 1's
ALREADY-allocated 12,729-row training pool (data/processed/
device1_train.csv), just revealed gradually instead of all at once --
no re-partitioning, no shrinking of any held-out set.

Reuses the REAL cloud Lambda handlers + moto-mocked AWS, same as
cloud/local_simulation.py (which this is structurally based on), so the
FedAvg coordination logic under test is identical to what would run
against real AWS.

Expectation set going in (memory.md §11e): 40-60% range with diminishing
returns, NOT 90%+. A result near 90% should be treated as a bug
(most likely eval-set contamination) to investigate, not a win to
report uncritically.

Run: python -m cloud.multiround_fuzzers_experiment
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
from model.evaluate import _load_test_df, classification_metrics, predict_all  # noqa: E402
from model.tabular_transformer import TabularTransformer  # noqa: E402

DEVICE_IDS = ["device1", "device2", "device3", "device4"]
CUMULATIVE_FRACS = [0.25, 0.5, 0.75, 1.0]  # % of device1's 12,729 Fuzzers rows revealed, by round
# order in which device1's Fuzzers rows are "encountered" -- canonical
# reported seed is 123; override via `python -m cloud.multiround_fuzzers_experiment 456`
# for a robustness re-run (memory.md §11f addendum).
SHUFFLE_SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 123


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


def _encode_buffer(df, encoder):
    return [(*encoder.encode_row(row), int(row["label"])) for _, row in df.iterrows()]


def main():
    with mock_aws():
        _provision_aws_resources()

        sys.path.insert(0, "cloud")
        import ingest_lambda.handler as ingest_h
        import model_lambda.handler as model_h
        from shared import store
        from shared.serialization import decode_state, encode_state

        encoder = SchemaEncoder("data/processed/vocab.json", "data/processed/scaler.json")
        backbone = _load_backbone()

        # ---- Device 1: split into a constant non-Fuzzers buffer + a
        # Fuzzers pool that gets revealed progressively. Shuffled once with
        # a fixed seed so "round 1" and "round 4" are nested (round 4's
        # pool is a superset of round 1's), matching a device that
        # accumulates traffic over time rather than replacing it.
        device1_df = pd.read_csv("data/processed/device1_train.csv")
        fuzzers_mask = device1_df["attack_cat"] == "Fuzzers"
        fuzzers_rows = device1_df[fuzzers_mask].sample(frac=1.0, random_state=SHUFFLE_SEED).reset_index(drop=True)
        other_rows = device1_df[~fuzzers_mask]
        n_total_fuzzers = len(fuzzers_rows)
        print(f"device1: {len(other_rows)} non-Fuzzers rows (constant across rounds), "
              f"{n_total_fuzzers} Fuzzers rows (revealed progressively: "
              f"{[int(f * n_total_fuzzers) for f in CUMULATIVE_FRACS]})")

        other_buffer_static = _encode_buffer(other_rows, encoder)

        models = {}
        for did in DEVICE_IDS:
            m = TabularTransformer(
                n_continuous=backbone.cont_proj.in_features,
                cat_cardinalities=[len(encoder.vocab[c]) for c in ["proto", "service", "state"]],
            )
            m.load_state_dict(backbone.state_dict())
            models[did] = InferenceModel(m, encoder)

        # Devices 2/3/4 keep their existing static local buffers, unchanged
        # from every prior experiment -- only device1's buffer changes here.
        buffers_234 = {
            did: _encode_buffer(pd.read_csv(f"data/processed/{did}_train.csv"), encoder)
            for did in DEVICE_IDS[1:]
        }

        # ---- Eval sets: both untouched by any training, this run or prior ----
        replay_df = pd.read_csv("data/processed/holdout_replay.csv")
        official_test_df = _load_test_df()
        official_fuzzers_df = official_test_df[official_test_df["attack_cat"] == "Fuzzers"]
        print(f"eval sets (untouched): holdout_replay.csv={len(replay_df)} rows, "
              f"official test={len(official_test_df)} rows "
              f"({len(official_fuzzers_df)} Fuzzers)")

        def eval_replay_fuzzers(inf_model):
            correct = 0
            for _, row in replay_df.iterrows():
                pred = inf_model.infer(row).argmax(dim=-1).item()
                correct += int(pred == row["label"])
            return correct / len(replay_df)

        def eval_official(inf_model):
            preds, labels = predict_all(inf_model, official_test_df)
            metrics = classification_metrics(preds, labels)
            f_preds, _ = predict_all(inf_model, official_fuzzers_df)
            fuzzers_recall = float((f_preds == 1).mean())
            return metrics, fuzzers_recall

        def upload(did, model_obj, trainer, new_adapter):
            event = {
                "body": json.dumps({
                    "device_id": did,
                    "n_samples": trainer.last_batch_size,
                    "local_val_accuracy": trainer.last_val_accuracy,
                    "weights": encode_state(_flatten_state(new_adapter)),
                })
            }
            result = ingest_h.handler(event, None)
            body = json.loads(result["body"])
            print(f"    {did}: n={trainer.last_batch_size} val_acc={trainer.last_val_accuracy:.4f} "
                  f"-> round={body['round']} aggregated={body['aggregated']}")

        def pull_all(since_round):
            event = {"queryStringParameters": {"since_round": str(since_round)}}
            for did in DEVICE_IDS:
                result = model_h.handler(event, None)
                assert result["statusCode"] == 200, f"{did} should see a new global model"
                body = json.loads(result["body"])
                global_adapter = _unflatten_state(decode_state(body["weights"]))
                models[did].load_adapter_state_dict(global_adapter)

        # ---- Baseline, before any round (all devices identical == frozen backbone) ----
        m0, fz0 = eval_official(models["device2"])
        r0 = eval_replay_fuzzers(models["device2"])
        print(f"\nBEFORE any round: official Fuzzers recall={fz0:.4f}, "
              f"replay Fuzzers acc={r0:.4f}, general acc={m0['accuracy']:.4f}, "
              f"general FPR={m0['false_positive_rate']:.4f}")

        results = [{
            "round": 0, "cum_frac": 0.0, "official_fuzzers_recall": fz0,
            "replay_fuzzers_acc": r0, "general_acc": m0["accuracy"],
            "general_fpr": m0["false_positive_rate"],
        }]

        for round_idx, frac in enumerate(CUMULATIVE_FRACS, start=1):
            n_reveal = int(n_total_fuzzers * frac)
            device1_buffer = other_buffer_static + _encode_buffer(fuzzers_rows.iloc[:n_reveal], encoder)
            print(f"\n=== ROUND {round_idx}: device1 sees {n_reveal}/{n_total_fuzzers} "
                  f"({frac * 100:.0f}%) cumulative Fuzzers rows ===")

            t0 = time.time()
            trainer1 = LocalTrainer(device1_buffer, epochs=5)
            adapter1 = trainer1.local_retrain(models["device1"].model)
            models["device1"].load_adapter_state_dict(adapter1)
            upload("device1", models["device1"], trainer1, adapter1)

            for did in DEVICE_IDS[1:]:
                trainer = LocalTrainer(buffers_234[did], epochs=5)
                adapter = trainer.local_retrain(models[did].model)
                models[did].load_adapter_state_dict(adapter)
                upload(did, models[did], trainer, adapter)

            state = store.get_round_state()
            assert state["latest_global_round"] == round_idx, \
                f"round {round_idx} should have auto-aggregated (all 4 devices reported)"

            pull_all(since_round=round_idx - 1)

            m, fz = eval_official(models["device2"])  # device2 never sees Fuzzers locally
            r = eval_replay_fuzzers(models["device2"])
            print(f"  round {round_idx} GLOBAL model ({time.time() - t0:.1f}s): "
                  f"official Fuzzers recall={fz:.4f}, replay Fuzzers acc={r:.4f}, "
                  f"general acc={m['accuracy']:.4f}, general FPR={m['false_positive_rate']:.4f}")

            results.append({
                "round": round_idx, "cum_frac": frac, "official_fuzzers_recall": fz,
                "replay_fuzzers_acc": r, "general_acc": m["accuracy"],
                "general_fpr": m["false_positive_rate"],
            })

        print("\n=== PROGRESSION SUMMARY (global model, measured on device2) ===")
        print(f"{'round':>5} {'cum%':>5} {'off.fuzzers':>12} {'replay.fuzzers':>15} "
              f"{'gen.acc':>8} {'gen.fpr':>8}")
        for r in results:
            print(f"{r['round']:>5} {r['cum_frac'] * 100:>4.0f}% {r['official_fuzzers_recall']:>12.4f} "
                  f"{r['replay_fuzzers_acc']:>15.4f} {r['general_acc']:>8.4f} {r['general_fpr']:>8.4f}")

        return results


if __name__ == "__main__":
    main()
