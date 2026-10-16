"""
model/operating_curve.py

Fuzzers recall of a FROZEN model when only its decision threshold is moved,
at the benign FPRs the federated runs end up at. If these match the federated
recall, federation bought an operating-point shift, not better separation.

Run: python -m model.operating_curve [checkpoint]   -> prints "RESULT_CURVE {...}"
     (no argument = frozen backbone; a path = a TabularTransformer checkpoint,
      e.g. model/baseline_centralized.pt)
"""
import json
import sys

import numpy as np
import torch
from sklearn.metrics import roc_auc_score

from edge_agent.inference import SchemaEncoder
from model.evaluate import _load_test_df
from model.tabular_transformer import TabularTransformer, load_backbone

ckpt = sys.argv[1] if len(sys.argv) > 1 else None
enc = SchemaEncoder("data/processed/vocab.json", "data/processed/scaler.json")
if ckpt:
    c = torch.load(ckpt, map_location="cpu")
    model = TabularTransformer(n_continuous=c["n_continuous"], cat_cardinalities=c["cat_cardinalities"])
    model.load_state_dict(c["model_state_dict"])
else:
    model = load_backbone()
model.eval()

test = _load_test_df()
rows = [enc.encode_row(r) for _, r in test.iterrows()]
xc, xk = torch.stack([e[0] for e in rows]), torch.stack([e[1] for e in rows])
with torch.no_grad():
    p = torch.cat([model(xc[i:i + 8192], xk[i:i + 8192]).softmax(-1)[:, 1] for i in range(0, len(test), 8192)]).numpy()
y = test["label"].astype(int).to_numpy()
fz = (test["attack_cat"] == "Fuzzers").to_numpy()
m = fz | (y == 0)
curve = {}
for fpr in (0.10, 0.143, 0.183, 0.185, 0.192, 0.212, 0.282, 0.331, 0.336, 0.36, 0.374):
    t = np.quantile(p[y == 0], 1 - fpr)
    curve[f"{fpr:.3f}"] = {"fuzzers_recall": float((p[fz] >= t).mean()), "attack_recall": float((p[y == 1] >= t).mean())}
print("RESULT_CURVE " + json.dumps({"model": ckpt or "backbone", "auroc": float(roc_auc_score(y, p)),
                                    "fuzzers_auroc": float(roc_auc_score(fz[m], p[m])), "curve": curve}))
