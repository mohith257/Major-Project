"""
model/evaluate_per_attack.py

Per-attack-category detection breakdown on the genuinely held-out test
sets (UNSW-NB15 + ToN_IoT), reusing model/evaluate.py's model + encoder +
batched predictor. For each category: how many flows it has and what
fraction the frozen global model flags as malicious.

  - attack categories  -> that % is the DETECTION RATE (recall) for that attack
  - Normal / benign    -> that % is the FALSE-POSITIVE RATE

These are REAL labelled held-out flows, not synthetic -- the standard way a
NIDS paper shows it handles DoS / DDoS / backdoor / recon / malware classes.
Run from the project root:  python -m model.evaluate_per_attack
"""
import json

from edge_agent.inference import InferenceModel, SchemaEncoder
from model.evaluate import (
    load_model, predict_all, _load_test_df, _load_ton_iot_test_df,
    VOCAB_PATH, SCALER_PATH,
)

BENIGN = {"normal", "benign", "0", ""}


def per_category(df, preds):
    cats = df["attack_cat"].astype(str).to_numpy()
    rows = []
    for cat in sorted(set(cats)):
        mask = cats == cat
        n = int(mask.sum())
        flagged = float((preds[mask] == 1).mean()) * 100
        rows.append((cat, n, round(flagged, 1)))
    # attacks first (desc by n), benign last
    rows.sort(key=lambda r: (r[0].lower() in BENIGN, -r[1]))
    return rows


def show(title, rows):
    print(f"\n=== {title} ===")
    print("  %-16s %8s   %-9s  %s" % ("category", "flows", "flagged", "meaning"))
    for cat, n, pct in rows:
        meaning = "FALSE-POSITIVE rate" if cat.lower() in BENIGN else "detection rate"
        print("  %-16s %8d   %5.1f%%     %s" % (cat, n, pct, meaning))


def main():
    model = load_model()
    enc = SchemaEncoder(VOCAB_PATH, SCALER_PATH)
    im = InferenceModel(model, enc)

    udf = _load_test_df()
    upreds, _ = predict_all(im, udf)
    urows = per_category(udf, upreds)
    show("UNSW-NB15 held-out test - per attack category", urows)

    tdf = _load_ton_iot_test_df()
    tpreds, _ = predict_all(im, tdf)
    trows = per_category(tdf, tpreds)
    show("ToN_IoT held-out test - per attack category", trows)

    return {
        "unsw": {c: {"n": n, "flagged_pct": p} for c, n, p in urows},
        "ton_iot": {c: {"n": n, "flagged_pct": p} for c, n, p in trows},
    }


if __name__ == "__main__":
    print("RESULT_PERATK " + json.dumps(main()))
