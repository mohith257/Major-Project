"""
cloud/ablation_experiment.py

Ablations for the paper, same protocol as multiround_fuzzers_experiment.py
(device1 reveals its Fuzzers pool 25/50/75/100% over 4 FedAvg rounds;
devices 2-4 static), but FedAvg is done in-process with the SAME
weighted_average() the aggregate Lambda uses (no moto, so it fits a 2 GB node).

Usage: python -m cloud.ablation_experiment <variant> <seed>
variants: lora_r1 lora_r2 lora_r4 lora_r8 full no_mining no_adv
          gated        -- every device adopts the global model only via
                          edge_agent.policy.gated_load on its own held-out data
          poison       -- device4 uploads a model-replacement attack
                          (-10 x its honest adapter), everyone adopts blindly
          poison_gated -- same attack, devices gate adoption
          fedprox      -- FedProx local objective, mu = 0.01
          median       -- coordinate-wise median aggregation instead of FedAvg
          poison_median-- poisoned client, median aggregation, no gate
          spread2/spread3 -- device1's Fuzzers pool split into 2/3 disjoint
                          shards held by device1..k (same total Fuzzers rows)
          long         -- 5x local steps per round (100/epoch instead of 20)
          spread3_long -- both
Prints one JSON line "RESULT {...}" with per-round metrics, payload bytes,
and (final round) accuracy under FGSM eps=0.05 on a 5,000-row test subsample.
"""
import json
import sys
import time

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from sklearn.metrics import roc_auc_score

from cloud.shared.serialization import coordinate_median, decode_state, encode_state, weighted_average
from edge_agent.comms import _flatten_state, _unflatten_state
from edge_agent.inference import InferenceModel, SchemaEncoder
from edge_agent.policy import gated_load
from edge_agent.trainer import LocalTrainer
from model.evaluate import _load_test_df, _load_ton_iot_test_df, classification_metrics, predict_all
from model.tabular_transformer import load_backbone, wrap_with_lora
import types

variant, seed = sys.argv[1], int(sys.argv[2])
torch.manual_seed(seed)
DEVICES = ["device1", "device2", "device3", "device4"]
FRACS = [0.25, 0.5, 0.75, 1.0]
rank = int(variant[6:]) if variant.startswith("lora_r") else 4
use_mining, use_adv = variant != "no_mining", variant != "no_adv"
gated, poisoned = variant in ("gated", "poison_gated"), variant.startswith("poison")
n_fz_clients = int(variant[6]) if variant.startswith("spread") else 1
steps = 100 if variant.endswith("long") else 20

enc = SchemaEncoder("data/processed/vocab.json", "data/processed/scaler.json")


def new_model():
    m = load_backbone()
    if variant == "full":  # every parameter trainable and federated
        m.adapter_state_dict = types.MethodType(lambda self: {n: p.detach().clone() for n, p in self.named_parameters()}, m)
        def _load(self, state):
            params = dict(self.named_parameters())
            with torch.no_grad():
                for n, t in state.items():
                    params[n].copy_(t)
        m.load_adapter_state_dict = types.MethodType(_load, m)
        m.trainable_parameters = types.MethodType(lambda self: self.parameters(), m)
    else:
        m = wrap_with_lora(m, r=rank, alpha=2 * rank)
    return m


def encode_buf(df):
    return [(*enc.encode_row(r), int(r["label"])) for _, r in df.iterrows()]


d1 = pd.read_csv("data/processed/device1_train.csv")
fz_mask = d1["attack_cat"] == "Fuzzers"
fz = d1[fz_mask].sample(frac=1.0, random_state=seed).reset_index(drop=True)
static1 = encode_buf(d1[~fz_mask])
bufs = {d: encode_buf(pd.read_csv(f"data/processed/{d}_train.csv")) for d in DEVICES[1:]}
models = {d: new_model() for d in DEVICES}
test = _load_test_df()
fz_test = test[test["attack_cat"] == "Fuzzers"]
replay = pd.read_csv("data/processed/holdout_replay.csv")


# Threshold-free view: is federation learning to separate Fuzzers from benign
# traffic, or just moving the decision threshold? AUROC + recall at a FIXED
# benign FPR (threshold set on the benign test rows) answer that.
_te = [enc.encode_row(r) for _, r in test.iterrows()]
te_xc, te_xk = torch.stack([e[0] for e in _te]), torch.stack([e[1] for e in _te])
te_y = test["label"].astype(int).to_numpy()
te_fz = (test["attack_cat"] == "Fuzzers").to_numpy()


def operating_point(m, fixed_fpr=0.10):
    m.eval()
    with torch.no_grad():
        p = torch.cat([m(te_xc[i:i + 8192], te_xk[i:i + 8192]).softmax(-1)[:, 1]
                       for i in range(0, len(te_y), 8192)]).numpy()
    t = np.quantile(p[te_y == 0], 1 - fixed_fpr)
    fz_vs_benign = te_fz | (te_y == 0)
    return {"auroc": float(roc_auc_score(te_y, p)),
            "fuzzers_auroc": float(roc_auc_score(te_fz[fz_vs_benign], p[fz_vs_benign])),
            "fuzzers_recall_at_fpr10": float((p[te_fz] >= t).mean()),
            "recall_at_fpr10": float((p[te_y == 1] >= t).mean())}


def evaluate(m):
    im = InferenceModel(m, enc)
    p, l = predict_all(im, test)
    met = classification_metrics(p, l)
    fp, _ = predict_all(im, fz_test)
    rp, rl = predict_all(im, replay)
    return {"acc": met["accuracy"], "fpr": met["false_positive_rate"], "macro_f1": met["macro_f1"],
            "fuzzers_recall": float((fp == 1).mean()), "replay_acc": float((rp == rl).mean()),
            **operating_point(m)}


def fgsm_acc(m, df, eps=0.05, n=5000):
    sub = df.sample(n=min(n, len(df)), random_state=0)
    enc_rows = [enc.encode_row(r) for _, r in sub.iterrows()]
    xc = torch.stack([e[0] for e in enc_rows]); xk = torch.stack([e[1] for e in enc_rows])
    y = torch.tensor(sub["label"].astype(int).to_numpy())
    m.eval()
    xa = xc.clone().requires_grad_(True)
    F.cross_entropy(m(xa, xk), y).backward()
    adv = (xc + eps * xa.grad.sign()).detach()
    with torch.no_grad():
        return float((m(xc, xk).argmax(-1) == y).float().mean()), float((m(adv, xk).argmax(-1) == y).float().mean())


rounds = [{"round": 0, **evaluate(models["device2"])}]
payload = 0
for r, frac in enumerate(FRACS, start=1):
    t0 = time.time()
    shards = np.array_split(np.arange(len(fz)), n_fz_clients)
    local = {d: static1 if d == "device1" else bufs[d] for d in DEVICES}
    for k, sh in enumerate(shards):
        local[DEVICES[k]] = local[DEVICES[k]] + encode_buf(fz.iloc[sh[:int(len(sh) * frac)]])
    subs, vals = [], {}
    for d in DEVICES:
        tr = LocalTrainer(local[d], epochs=5, steps_per_epoch=steps, use_hard_mining=use_mining,
                          use_adversarial=use_adv, prox_mu=0.01 if variant == "fedprox" else 0.0)
        st = tr.local_retrain(models[d])
        vals[d] = tr.val_buffer
        if poisoned and d == "device4":
            st = {k: -10 * v for k, v in st.items()}
        wire = encode_state(_flatten_state(st))
        payload = sum(len(v["data_b64"]) * 3 // 4 for v in wire.values())
        subs.append((decode_state(wire), tr.last_batch_size))
    g = _unflatten_state((coordinate_median if variant.endswith("median") else weighted_average)(subs))
    accepted = {}
    for d in DEVICES:
        if gated:
            accepted[d] = gated_load(models[d], g, vals[d])[0]
        else:
            models[d].load_adapter_state_dict(g)
    rounds.append({"round": r, "secs": round(time.time() - t0, 1), "accepted": accepted, **evaluate(models["device2"])})
    print(f"round {r}: {rounds[-1]}", flush=True)

clean, adv = fgsm_acc(models["device2"], test)
ton_p, ton_l = predict_all(InferenceModel(models["device2"], enc), _load_ton_iot_test_df())
ton = classification_metrics(ton_p, ton_l)
print("RESULT " + json.dumps({"variant": variant, "seed": seed, "payload_bytes": payload, "rounds": rounds,
      "fgsm_clean_acc": clean, "fgsm_adv_acc": adv, "ton_acc": ton["accuracy"], "ton_fpr": ton["false_positive_rate"]}))
