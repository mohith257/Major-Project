"""
model/type_infer.py

Stage-2 attack-TYPE inference. Loads the artifact saved by
model/train_type_stage2.py (weights + scaler + categorical encoders, all in
one torch file) and labels a raw UNSW-schema flow with one of the 9 attack
types. Completely separate from the deployed binary detector -- this only
runs on full-feature (replay) flows, never on the 8-feature live wire.

    tc = TypeClassifier()                      # loads model/type_unsw.pt
    label, conf = tc.predict_one(raw_row_dict) # raw UNSW row (dict/Series)

The binary detector is the Normal-vs-attack gate; this model assumes the
flow is already an attack and only answers "which type".
"""
import numpy as np
import pandas as pd
import torch

from model.tabular_transformer import TabularTransformer

DEFAULT_PATH = "model/type_unsw.pt"


class TypeClassifier:
    def __init__(self, path=DEFAULT_PATH, device="cpu"):
        ckpt = torch.load(path, weights_only=False)
        self.model = TabularTransformer(
            n_continuous=ckpt["n_continuous"],
            cat_cardinalities=ckpt["cat_cardinalities"],
            **ckpt["arch"],
        ).to(device)
        self.model.load_state_dict(ckpt["model_state_dict"])
        self.model.eval()
        self.device = device
        self.num_cols = ckpt["num_cols"]
        self.cat_cols = ckpt["cat_cols"]
        self.skew_cols = set(ckpt["skew_cols"])
        self.classes = ckpt["classes"]
        self.scaler = ckpt["scaler"]
        # precompute {value -> index} per categorical, with an unseen fallback
        # (LabelEncoder.transform raises on an unknown value; a live flow will
        # eventually carry a proto/service the training set never saw).
        self.cat_index = {
            c: {v: i for i, v in enumerate(enc.classes_)}
            for c, enc in ckpt["cat_encoders"].items()
        }

    def _prep_num(self, df):
        X = df[self.num_cols].astype(float).copy()
        for c in self.num_cols:
            if c in self.skew_cols:
                X[c] = np.log1p(X[c].clip(lower=0))
        arr = np.nan_to_num(X.to_numpy(), nan=0.0, posinf=0.0, neginf=0.0)
        return self.scaler.transform(arr)

    def _prep_cat(self, df):
        out = np.zeros((len(df), len(self.cat_cols)), dtype=np.int64)
        for j, c in enumerate(self.cat_cols):
            table = self.cat_index[c]
            out[:, j] = [table.get(str(v), 0) for v in df[c]]  # 0 = unseen fallback
        return out

    def predict(self, rows):
        """rows: DataFrame (or list of dicts) of raw UNSW-schema flows.
        Returns (labels, confidences) as parallel lists."""
        df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(list(rows))
        x_cont = torch.tensor(self._prep_num(df), dtype=torch.float32, device=self.device)
        x_cat = torch.tensor(self._prep_cat(df), dtype=torch.long, device=self.device)
        with torch.no_grad():
            probs = torch.softmax(self.model(x_cont, x_cat), dim=-1)
        conf, idx = probs.max(dim=-1)
        labels = [self.classes[i] for i in idx.tolist()]
        return labels, conf.tolist()

    def predict_one(self, row):
        labels, confs = self.predict([dict(row)])
        return labels[0], confs[0]
