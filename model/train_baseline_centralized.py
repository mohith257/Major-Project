"""
model/train_baseline_centralized.py

The baseline this project's federated result needs to be measured against:
"what if we skipped privacy-preserving federation entirely and just
pooled all 4 devices' raw local data centrally, including Fuzzers?" --
the exact counterfactual the project's privacy claim is defending against.

Unlike model/train_backbone.py (which deliberately EXCLUDES the hold-out
class and ships the result to be LoRA-adapted per device), this trains one
model, once, on the union of device{1..4}_train.csv (raw local partitions,
Fuzzers included since a real centralized system has no reason to hide
it), evaluates it on the exact same two held-out test sets as
model/evaluate.py, and never gets deployed anywhere -- it exists purely
as a reference point for the paper's "compared to what?" table.

Run: python -m model.train_baseline_centralized
"""
import pandas as pd
import torch
import torch.nn as nn
from sklearn.model_selection import train_test_split

from data.scripts.partition_data import CANONICAL_CONTINUOUS
from edge_agent.inference import InferenceModel, SchemaEncoder
from model.evaluate import (
    _load_test_df,
    _load_ton_iot_test_df,
    classification_metrics,
    predict_all,
)
from model.tabular_transformer import TabularTransformer

DEVICE_FILES = [f"data/processed/device{i}_train.csv" for i in range(1, 5)]
VOCAB_PATH = "data/processed/vocab.json"
SCALER_PATH = "data/processed/scaler.json"
CHECKPOINT_PATH = "model/baseline_centralized.pt"


def load_pooled_dataset(encoder: SchemaEncoder):
    df = pd.concat([pd.read_csv(f) for f in DEVICE_FILES], ignore_index=True)
    print(f"pooled centralized training set: {len(df)} rows "
          f"(union of device1-4_train.csv, Fuzzers included -- the exact "
          f"data a non-federated, non-privacy-preserving system would "
          f"just train on directly)")
    conts, cats = [], []
    for _, row in df.iterrows():
        x_cont, x_cat = encoder.encode_row(row)
        conts.append(x_cont)
        cats.append(x_cat)
    x_cont = torch.stack(conts)
    x_cat = torch.stack(cats)
    labels = torch.tensor(df["label"].values, dtype=torch.long)
    return x_cont, x_cat, labels


def train(epochs=10, lr=1e-3, batch_size=256, device="cpu"):
    encoder = SchemaEncoder(VOCAB_PATH, SCALER_PATH)
    x_cont, x_cat, labels = load_pooled_dataset(encoder)

    x_cont_tr, x_cont_val, x_cat_tr, x_cat_val, y_tr, y_val = train_test_split(
        x_cont, x_cat, labels, test_size=0.1, stratify=labels, random_state=42
    )

    model = TabularTransformer(
        n_continuous=len(CANONICAL_CONTINUOUS),
        cat_cardinalities=encoder.cardinalities(),
    ).to(device)
    # Full model, no LoRA restriction -- this is the whole point of the
    # baseline (2026-09-21: moot now that LoRA wrapping happens via
    # peft.wrap_with_lora() only after pretraining, not at construction --
    # this model is already fully trainable by default).
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.CrossEntropyLoss()

    n = len(y_tr)
    for epoch in range(epochs):
        model.train()
        perm = torch.randperm(n)
        total_loss = 0.0
        for i in range(0, n, batch_size):
            idx = perm[i : i + batch_size]
            opt.zero_grad()
            logits = model(x_cont_tr[idx].to(device), x_cat_tr[idx].to(device))
            loss = loss_fn(logits, y_tr[idx].to(device))
            loss.backward()
            opt.step()
            total_loss += loss.item() * len(idx)

        model.eval()
        with torch.no_grad():
            val_logits = model(x_cont_val.to(device), x_cat_val.to(device))
            val_acc = (val_logits.argmax(dim=-1).cpu() == y_val).float().mean().item()
        print(
            f"epoch {epoch + 1}/{epochs}  "
            f"train_loss={total_loss / n:.4f}  val_acc={val_acc:.4f}"
        )

    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "n_continuous": len(CANONICAL_CONTINUOUS),
            "cat_cardinalities": encoder.cardinalities(),
        },
        CHECKPOINT_PATH,
    )
    print(f"saved centralized baseline -> {CHECKPOINT_PATH}")
    return model, encoder


def evaluate_against_held_out(model, encoder):
    inference_model = InferenceModel(model, encoder)

    test_df = _load_test_df()
    preds, labels = predict_all(inference_model, test_df)
    unsw_metrics = classification_metrics(preds, labels)

    fuzzers_df = test_df[test_df["attack_cat"] == "Fuzzers"]
    f_preds, _ = predict_all(inference_model, fuzzers_df)
    fuzzers_recall = float((f_preds == 1).mean())

    tonio_df = _load_ton_iot_test_df()
    t_preds, t_labels = predict_all(inference_model, tonio_df)
    tonio_metrics = classification_metrics(t_preds, t_labels)

    print("\n== Centralized baseline vs. same held-out test sets as the federated system ==")
    print(f"UNSW-NB15: accuracy={unsw_metrics['accuracy']:.4f} macro_f1={unsw_metrics['macro_f1']:.4f} "
          f"fpr={unsw_metrics['false_positive_rate']:.4f} fuzzers_recall={fuzzers_recall:.4f}")
    print(f"ToN_IoT:   accuracy={tonio_metrics['accuracy']:.4f} macro_f1={tonio_metrics['macro_f1']:.4f} "
          f"fpr={tonio_metrics['false_positive_rate']:.4f}")
    return {"unsw": unsw_metrics, "fuzzers_recall": fuzzers_recall, "ton_iot": tonio_metrics}


if __name__ == "__main__":
    model, encoder = train()
    evaluate_against_held_out(model, encoder)
