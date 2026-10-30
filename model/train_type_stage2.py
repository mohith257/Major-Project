"""
model/train_type_stage2.py

Stage-2 ATTACK-TYPE classifier for the two-stage deployment:

    live flow -> [binary detector | already deployed]  -> BLOCK if attack
                              |
                              v  (only attack-flagged flows)
                 [this model] -> which of 9 attack types

So this model is trained on ATTACKS ONLY -- the Normal class is removed. The
binary detector is the Normal-vs-attack gate; this head only has to
discriminate AMONG attack types. That kills the 36%-of-Normal-misclassified
problem from train_type_classifier.py and lets us use far milder class
weighting, which recovers precision.

Full UNSW feature set (39 numeric + proto/service/state). Not federated, not
the 8-feature live schema -- separate benchmark model for the type label.

Run:  python -u -m model.train_type_stage2
"""
import json
import os
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.metrics import classification_report, confusion_matrix, balanced_accuracy_score

from model.tabular_transformer import TabularTransformer

TRAIN = "data/raw/unsw_nb15_train.csv"
TEST = "data/raw/unsw_nb15_test.csv"
CAT = ["proto", "service", "state"]
DROP = ["id", "attack_cat", "label"] + CAT
SKEW = ["dur", "sbytes", "dbytes", "rate", "sload", "dload", "sinpkt", "dinpkt",
        "sjit", "djit", "stcpb", "dtcpb", "smean", "dmean", "response_body_len"]

EPOCHS = 14   # quality plateaus by ~12 (verified on the full 22-epoch run);
              # deployed weights don't need the extra half-hour of CPU.
SEED = 0
WEIGHT_CAP = 5.0  # max/min class-weight ratio -- soft, so rare classes get a
                  # nudge without Shellcode/Worms hijacking the loss.


def prep_num(df, num_cols):
    X = df[num_cols].astype(float).copy()
    for c in SKEW:
        if c in X.columns:
            X[c] = np.log1p(X[c].clip(lower=0))
    return np.nan_to_num(X.to_numpy(), nan=0.0, posinf=0.0, neginf=0.0)


def main():
    torch.manual_seed(SEED)
    torch.set_num_threads(os.cpu_count() or 4)   # use every core on CPU
    tr = pd.read_csv(TRAIN)
    te = pd.read_csv(TEST)

    # two-stage: drop Normal entirely. The binary detector is the gate.
    tr = tr[tr["attack_cat"].astype(str) != "Normal"].reset_index(drop=True)
    te = te[te["attack_cat"].astype(str) != "Normal"].reset_index(drop=True)

    num_cols = [c for c in tr.columns if c not in DROP]

    sc = StandardScaler().fit(prep_num(tr, num_cols))
    Xtr_n = torch.tensor(sc.transform(prep_num(tr, num_cols)), dtype=torch.float32)
    Xte_n = torch.tensor(sc.transform(prep_num(te, num_cols)), dtype=torch.float32)

    cards = []
    cat_encoders = {}
    Xtr_c = np.zeros((len(tr), len(CAT)), dtype=np.int64)
    Xte_c = np.zeros((len(te), len(CAT)), dtype=np.int64)
    for i, c in enumerate(CAT):
        le = LabelEncoder().fit(pd.concat([tr[c], te[c]]).astype(str))
        cat_encoders[c] = le
        cards.append(len(le.classes_))
        Xtr_c[:, i] = le.transform(tr[c].astype(str))
        Xte_c[:, i] = le.transform(te[c].astype(str))
    Xtr_c = torch.tensor(Xtr_c)
    Xte_c = torch.tensor(Xte_c)

    lab = LabelEncoder().fit(tr["attack_cat"].astype(str))
    classes = list(lab.classes_)
    n_classes = len(classes)
    ytr = torch.tensor(lab.transform(tr["attack_cat"].astype(str)))
    yte = torch.tensor(lab.transform(te["attack_cat"].astype(str)))

    counts = np.bincount(ytr.numpy(), minlength=n_classes)
    # mild inverse-sqrt, then CAP the max/min ratio so Worms (n~130) can't
    # dominate. This is the knob that was too hot in the previous run.
    w = 1.0 / np.sqrt(counts + 1.0)
    w = np.clip(w, None, w.min() * WEIGHT_CAP)   # cap the biggest boost at 5x
    w = w / w.sum() * n_classes
    cw = torch.tensor(w, dtype=torch.float32)
    print("class weights:", {c: round(float(x), 2) for c, x in zip(classes, w)})

    model = TabularTransformer(
        n_continuous=len(num_cols), cat_cardinalities=cards,
        d_model=64, n_heads=4, n_layers=3, n_classes=n_classes,
        per_feature_tokens=True,
    )
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)
    loss_fn = nn.CrossEntropyLoss(weight=cw)

    bs, n = 512, len(ytr)
    for ep in range(EPOCHS):
        model.train()
        perm = torch.randperm(n)
        tot = 0.0
        for i in range(0, n, bs):
            idx = perm[i:i + bs]
            opt.zero_grad()
            out = model(Xtr_n[idx], Xtr_c[idx])
            loss = loss_fn(out, ytr[idx])
            loss.backward()
            opt.step()
            tot += loss.item() * len(idx)
        model.eval()
        with torch.no_grad():
            pred = torch.cat([model(Xte_n[i:i + 4096], Xte_c[i:i + 4096]).argmax(-1)
                              for i in range(0, len(yte), 4096)])
        acc = (pred == yte).float().mean().item()
        bal = balanced_accuracy_score(yte.numpy(), pred.numpy())
        print(f"epoch {ep + 1:2d}/{EPOCHS}  loss={tot / n:.4f}  test_acc={acc:.4f}  balanced_acc={bal:.4f}", flush=True)

    print("\n=== per-class report (UNSW-NB15 test, ATTACKS ONLY) ===")
    print(classification_report(yte.numpy(), pred.numpy(), target_names=classes, digits=3, zero_division=0))
    print("rows per class (test):")
    for c, k in zip(classes, np.bincount(yte.numpy(), minlength=n_classes)):
        print(f"  {c:16s} {k}")

    cm = confusion_matrix(yte.numpy(), pred.numpy())
    out = {
        "classes": classes,
        "note": "attacks-only type head; binary detector is the Normal gate",
        "test_accuracy": float((pred == yte).float().mean().item()),
        "balanced_accuracy": float(balanced_accuracy_score(yte.numpy(), pred.numpy())),
        "confusion_matrix": cm.tolist(),
        "recall_per_class": {c: float((cm[i, i] / cm[i].sum()) if cm[i].sum() else 0.0)
                             for i, c in enumerate(classes)},
    }
    os.makedirs("paper_figures/type_classifier", exist_ok=True)
    with open("paper_figures/type_classifier/unsw_type_stage2_results.json", "w") as f:
        json.dump(out, f, indent=2)
    print("\nsaved -> paper_figures/type_classifier/unsw_type_stage2_results.json")

    # Persist everything inference needs in ONE artifact. torch.save pickles
    # the sklearn scaler/encoders alongside the weights; model/type_infer.py
    # loads it with weights_only=False (same convention as load_backbone).
    torch.save({
        "model_state_dict": model.state_dict(),
        "n_continuous": len(num_cols),
        "cat_cardinalities": cards,
        "arch": {"d_model": 64, "n_heads": 4, "n_layers": 3,
                 "n_classes": n_classes, "per_feature_tokens": True},
        "num_cols": num_cols,
        "cat_cols": CAT,
        "skew_cols": SKEW,
        "classes": classes,
        "scaler": sc,
        "cat_encoders": cat_encoders,
    }, "model/type_unsw.pt")
    print("saved -> model/type_unsw.pt")


if __name__ == "__main__":
    main()
