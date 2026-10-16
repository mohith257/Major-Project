"""
model/gbm_reference.py

Non-neural reference for the paper: a gradient-boosted tree trained on the
SAME data (central_pretrain_pool.csv, Fuzzers excluded) and SAME eight
canonical features as the backbone, scored on the same test sets. Answers
"how much of the official-split gap is the Transformer itself?".

Run: python -m model.gbm_reference <seed>   -> prints "RESULT_GBM {...}"
"""
import json
import sys
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from data.scripts.partition_data import CANONICAL_CATEGORICAL, CANONICAL_CONTINUOUS
from model.evaluate import _load_test_df, _load_ton_iot_test_df, classification_metrics

seed = int(sys.argv[1]) if len(sys.argv) > 1 else 0
vocab = json.load(open("data/processed/vocab.json"))


def features(df):
    x = np.log1p(df[CANONICAL_CONTINUOUS].clip(lower=0).to_numpy(dtype=float))
    cats = [df[c].astype(str).map({v: i for i, v in enumerate(vocab[c])}).fillna(len(vocab[c]) - 1).to_numpy()
            for c in CANONICAL_CATEGORICAL]
    return np.column_stack([x, *cats])


n_cont = len(CANONICAL_CONTINUOUS)
pool = pd.read_csv("data/processed/central_pretrain_pool.csv")
gbm = HistGradientBoostingClassifier(max_iter=300, early_stopping=True, validation_fraction=0.15, random_state=seed,
                                     categorical_features=list(range(n_cont, n_cont + len(CANONICAL_CATEGORICAL))))
gbm.fit(features(pool), pool["label"].astype(int).to_numpy())

test, ton = _load_test_df(), _load_ton_iot_test_df()
p = gbm.predict(features(test))
unsw = classification_metrics(p, test["label"].astype(int).to_numpy())
fz = float(p[(test["attack_cat"] == "Fuzzers").to_numpy()].mean())
tp = gbm.predict(features(ton))
ton_m = classification_metrics(tp, ton["label"].astype(int).to_numpy())
t0 = time.perf_counter()
gbm.predict(features(test.iloc[:1]))
print("RESULT_GBM " + json.dumps({"seed": seed, "unsw": unsw, "fuzzers_recall": fz, "ton_iot": ton_m,
                                  "single_row_ms": 1000 * (time.perf_counter() - t0)}, default=float))
