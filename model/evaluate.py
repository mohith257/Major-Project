"""
model/evaluate.py

Real evaluation metrics against genuinely held-out data -- fixes a gap
flagged earlier in this project: `unsw_nb15_test.csv` was downloaded but
never used anywhere, so "validation accuracy" only ever meant an internal
15% split carved out of the training pool itself. This is the actual,
independent test set, never touched by central pretraining OR any
device's local data (see data/scripts/partition_data.py -- only
unsw_nb15_train.csv feeds the pipeline).

Computes everything promised in the synopsis's evaluation-metrics section
that hadn't been measured at all until now: Precision, Recall, Macro F1,
False Positive Rate, inference latency, and adapter payload size. Also
defines a Drift Recovery Index proxy for the Fuzzers hold-out scenario --
labeled explicitly as OUR OWN definition, since Vijetha (2026)/AISAF's
exact formula wasn't detailed enough in the reviewed excerpt to replicate.

Evaluates BOTH datasets independently, each against genuinely held-out
data (see below for how the ToN_IoT split was made to exist).

ToN_IoT has no official train/test split (unlike UNSW-NB15), so
data/scripts/partition_data.py's `carve_test_split()` now carves one
ourselves -- stratified by attack category, held out before anything
trains on it. `data/processed/ton_iot_test.csv` is that genuine held-out
set; this module evaluates both sides independently.
"""
import json
import time

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

from cloud.shared.serialization import encode_state
from data.scripts.partition_data import (
    UNSW_NB15_MAPPING,
    bucket_proto,
    bucket_state,
    load_and_map,
    synthesize_ip,
)
from edge_agent.comms import _flatten_state
from edge_agent.inference import InferenceModel, SchemaEncoder
from model.tabular_transformer import TabularTransformer, wrap_with_lora

CHECKPOINT_PATH = "model/backbone_frozen.pt"
VOCAB_PATH = "data/processed/vocab.json"
SCALER_PATH = "data/processed/scaler.json"
TEST_PATH = "data/raw/unsw_nb15_test.csv"
TON_IOT_TEST_PATH = "data/processed/ton_iot_test.csv"


def load_model():
    """Wraps with peft's LoRA (wrap_with_lora) before returning -- matches
    what a real edge device actually runs (run_edge_node.py's
    build_model()), which matters here since measure_payload_size() needs
    a real adapter_state_dict() to measure, and it keeps this evaluation
    honest about testing the same code path as production."""
    ckpt = torch.load(CHECKPOINT_PATH, weights_only=False)
    model = TabularTransformer(
        n_continuous=ckpt["n_continuous"], cat_cardinalities=ckpt["cat_cardinalities"]
    )
    model.load_state_dict(ckpt["model_state_dict"])
    return wrap_with_lora(model)


def predict_all(inference_model, df, batch_size=4096):
    """Batched, not one Python-level forward pass per row -- the original
    row-by-row version took multiple minutes over the 82K-row test set
    purely from per-call Python/tensor overhead, not actual model compute.
    Chunks of batch_size keep memory bounded on larger test sets."""
    model = inference_model.model
    encoder = inference_model.encoder
    all_preds = []
    rows = list(df.iterrows())
    model.eval()
    with torch.no_grad():
        for start in range(0, len(rows), batch_size):
            chunk = rows[start:start + batch_size]
            encoded = [encoder.encode_row(r) for _, r in chunk]
            x_cont = torch.stack([e[0] for e in encoded])
            x_cat = torch.stack([e[1] for e in encoded])
            logits = model(x_cont, x_cat)
            all_preds.append(logits.argmax(dim=-1))
    preds = torch.cat(all_preds).numpy()
    labels = df["label"].astype(int).to_numpy()
    return preds, labels


def classification_metrics(preds, labels):
    precision, recall, _, _ = precision_recall_fscore_support(
        labels, preds, average=None, labels=[0, 1], zero_division=0
    )
    macro_f1 = precision_recall_fscore_support(
        labels, preds, average="macro", zero_division=0
    )[2]
    tn, fp, fn, tp = confusion_matrix(labels, preds, labels=[0, 1]).ravel()
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    accuracy = float((preds == labels).mean())
    return {
        "accuracy": accuracy,
        "precision_normal": float(precision[0]), "precision_attack": float(precision[1]),
        "recall_normal": float(recall[0]), "recall_attack": float(recall[1]),
        "macro_f1": float(macro_f1),
        "false_positive_rate": float(fpr),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def measure_latency(inference_model, df, n=200):
    sample = df.sample(n=min(n, len(df)), random_state=42)
    times = []
    for _, row in sample.iterrows():
        t0 = time.perf_counter()
        inference_model.infer(row)
        times.append((time.perf_counter() - t0) * 1000)
    return {
        "mean_ms": float(np.mean(times)), "median_ms": float(np.median(times)),
        "p95_ms": float(np.percentile(times, 95)), "n_samples": len(times),
    }


def measure_payload_size(model):
    wire = encode_state(_flatten_state(model.adapter_state_dict()))
    n_bytes = len(json.dumps(wire).encode("utf-8"))
    return {"adapter_json_bytes": n_bytes, "adapter_json_kb": round(n_bytes / 1024, 2)}


def drift_recovery_index(acc_before, acc_after):
    """Fraction of the maximum possible recoverable accuracy gap that one
    local retrain actually closed: (after - before) / (1 - before).
    1.0 = perfect recovery to 100%, 0.0 = no improvement, negative = got
    worse. OUR OWN definition -- not claimed to match AISAF's formula."""
    denom = 1.0 - acc_before
    if denom <= 0:
        return 0.0
    return (acc_after - acc_before) / denom


def _load_test_df():
    df = load_and_map(TEST_PATH, UNSW_NB15_MAPPING)
    df = synthesize_ip(df)
    df["proto"] = df["proto"].apply(bucket_proto)
    df["state"] = df["state"].apply(bucket_state)
    return df


def _load_ton_iot_test_df():
    """Already in canonical schema (bucketed proto/state) -- written
    directly by data/scripts/partition_data.py's carve_test_split(), no
    re-mapping needed here unlike the raw UNSW-NB15 file."""
    return pd.read_csv(TON_IOT_TEST_PATH)


def main():
    model = load_model()
    encoder = SchemaEncoder(VOCAB_PATH, SCALER_PATH)
    inference_model = InferenceModel(model, encoder)

    test_df = _load_test_df()
    fuzzers_n = len(test_df[test_df["attack_cat"] == "Fuzzers"])
    print(f"evaluating against {len(test_df)} genuinely held-out UNSW-NB15 test rows")
    print(f"(includes {fuzzers_n} Fuzzers rows -- the frozen backbone was never "
          f"trained on this class, from either the train OR test split)")

    preds, labels = predict_all(inference_model, test_df)
    metrics = classification_metrics(preds, labels)
    print("\n== General classification metrics (frozen global model) ==")
    for k, v in metrics.items():
        print(f"  {k}: {v}")

    fuzzers_df = test_df[test_df["attack_cat"] == "Fuzzers"]
    f_preds, _ = predict_all(inference_model, fuzzers_df)
    fuzzers_recall = float((f_preds == 1).mean())
    print("\n== Fuzzers-specific recall (frozen model, independent test split) ==")
    print(f"  {fuzzers_recall:.4f} over {len(fuzzers_df)} rows")

    latency = measure_latency(inference_model, test_df)
    print("\n== Inference latency (single-sample, this CPU) ==")
    for k, v in latency.items():
        print(f"  {k}: {v}")

    payload = measure_payload_size(model)
    print("\n== Adapter payload size (what actually crosses the network) ==")
    print(f"  {payload['adapter_json_bytes']} bytes ({payload['adapter_json_kb']} KB)")

    tonio_test_df = _load_ton_iot_test_df()
    print(f"\nevaluating against {len(tonio_test_df)} genuinely held-out ToN_IoT test "
          f"rows (carve_test_split, never touched by training)")
    t_preds, t_labels = predict_all(inference_model, tonio_test_df)
    tonio_metrics = classification_metrics(t_preds, t_labels)
    print("\n== ToN_IoT general classification metrics (frozen global model) ==")
    for k, v in tonio_metrics.items():
        print(f"  {k}: {v}")

    return {
        "unsw": metrics, "fuzzers_recall": fuzzers_recall,
        "ton_iot": tonio_metrics, "latency": latency, "payload": payload,
    }


if __name__ == "__main__":
    main()
