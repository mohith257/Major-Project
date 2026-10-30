"""
model/train_type_classifier.py

Benchmark-only multi-class ATTACK-TYPE classifier on the FULL UNSW-NB15 feature
set (39 numeric + proto/service/state) -- NOT the 8-feature live schema, and
NOT federated. It exists to answer one question: does richer features + class
balancing actually lift the weak classes (Shellcode, Worms) that the live
8-feature binary detector misses? It is completely separate from the deployed
federated pipeline and touches nothing that runs on the nodes.

Run:  python -m model.train_type_classifier
"""
import json
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
# heavy-tailed -> log1p before standardizing
SKEW = ["dur", "sbytes", "dbytes", "rate", "sload", "dload", "sinpkt", "dinpkt",
        "sjit", "djit", "stcpb", "dtcpb", "smean", "dmean", "response_body_len"]

EPOCHS = 18
SEED = 0


def prep_num(df, num_cols):
    X = df[num_cols].astype(float).copy()
    for c in SKEW:
        if c in X.columns:
            X[c] = np.log1p(X[c].clip(lower=0))
    return np.nan_to_num(X.to_numpy(), nan=0.0, posinf=0.0, neginf=0.0)


def main():
    torch.manual_seed(SEED)
    tr = pd.read_csv(TRAIN)
    te = pd.read_csv(TEST)
    num_cols = [c for c in tr.columns if c not in DROP]

    sc = StandardScaler().fit(prep_num(tr, num_cols))
    Xtr_n = torch.tensor(sc.transform(prep_num(tr, num_cols)), dtype=torch.float32)
    Xte_n = torch.tensor(sc.transform(prep_num(te, num_cols)), dtype=torch.float32)

    cards = []
    Xtr_c = np.zeros((len(tr), len(CAT)), dtype=np.int64)
    Xte_c = np.zeros((len(te), len(CAT)), dtype=np.int64)
    for i, c in enumerate(CAT):
        le = LabelEncoder().fit(pd.concat([tr[c], te[c]]).astype(str))
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
    # inverse-sqrt-frequency weights: helps rare classes without letting
    # Worms (n=130) completely dominate the loss.
    w = 1.0 / np.sqrt(counts + 1.0)
    w = w / w.sum() * n_classes
    cw = torch.tensor(w, dtype=torch.float32)

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
        print(f"epoch {ep + 1:2d}/{EPOCHS}  loss={tot / n:.4f}  test_acc={acc:.4f}  balanced_acc={bal:.4f}")

    print("\n=== per-class report (UNSW-NB15 official test split) ===")
    print(classification_report(yte.numpy(), pred.numpy(), target_names=classes, digits=3, zero_division=0))
    print("rows per class (test):")
    for c, k in zip(classes, np.bincount(yte.numpy(), minlength=n_classes)):
        print(f"  {c:16s} {k}")

    cm = confusion_matrix(yte.numpy(), pred.numpy())
    out = {
        "classes": classes,
        "test_accuracy": float((pred == yte).float().mean().item()),
        "balanced_accuracy": float(balanced_accuracy_score(yte.numpy(), pred.numpy())),
        "confusion_matrix": cm.tolist(),
        "recall_per_class": {c: float((cm[i, i] / cm[i].sum()) if cm[i].sum() else 0.0)
                             for i, c in enumerate(classes)},
    }
    import os
    os.makedirs("paper_figures/type_classifier", exist_ok=True)
    with open("paper_figures/type_classifier/unsw_type_results.json", "w") as f:
        json.dump(out, f, indent=2)
    print("\nsaved -> paper_figures/type_classifier/unsw_type_results.json")


if __name__ == "__main__":
    main()
