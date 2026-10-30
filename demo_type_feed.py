"""
demo_type_feed.py -- two-stage demo: binary detector BLOCKS, type model LABELS.

Streams REAL held-out UNSW-NB15 test attacks (full 42-feature rows) through
BOTH models the way the deployed two-stage pipeline does:

    raw flow --> [binary detector]  P(attack) -> BLOCK/ALERT/NOOP   (deployed, 8 feat)
                      |
                      v  (attack-flagged)
             [stage-2 type model] -> one of 9 UNSW attack types      (full 42 feat)

Each verdict is POSTed to the live API with an extra `attack_type` field, so the
hosted dashboard's Incident Feed shows BOTH the action and the attack type. The
binary path is untouched -- this only ADDS a type label on full-feature flows.

Honesty line for the viva: real held-out test flows (not live wire, not
fabricated). The binary detector outputs P(attack) exactly as a node does; the
type model's label is its own prediction (we also carry the dataset's
ground-truth type as `attack_type_true` so a wrong guess is visible, not hidden).
Reported under device_id "type-demo" so it never masquerades as a live node.

Meant to run on an always-on EC2 node (it has torch + the models); judges just
open the website. Run from repo root:

    API_BASE_URL=... API_KEY=... python demo_type_feed.py --report --hz 2
"""
import argparse
import collections
import itertools
import os
import time

import numpy as np
import pandas as pd
import torch

from edge_agent.inference import InferenceModel, SchemaEncoder
from edge_agent.policy import choose_action, threshold_action
from model.tabular_transformer import load_backbone, wrap_with_lora
from model.type_infer import TypeClassifier
from data.scripts.partition_data import (
    UNSW_NB15_MAPPING, CANONICAL_CONTINUOUS, CANONICAL_CATEGORICAL,
    bucket_proto, bucket_state, synthesize_ip,
)

ap = argparse.ArgumentParser()
ap.add_argument("--csv", default="data/raw/unsw_nb15_test.csv")
ap.add_argument("--hz", type=float, default=2.0, help="flows per second")
ap.add_argument("--policy", choices=["cost", "threshold"], default="cost")
ap.add_argument("--block-confidence", type=float, default=0.65)
ap.add_argument("--limit", type=int, default=0, help="stop after N flows (0 = until Ctrl-C)")
ap.add_argument("--report", action="store_true", help="POST each verdict to the live API")
ap.add_argument("--api-base", default=os.environ.get("API_BASE_URL"))
ap.add_argument("--api-key", default=os.environ.get("API_KEY"))
ap.add_argument("--device", default="type-demo")
args = ap.parse_args()

# --- models ---------------------------------------------------------------
encoder = SchemaEncoder("data/processed/vocab.json", "data/processed/scaler.json")
binary = InferenceModel(wrap_with_lora(load_backbone("model/backbone_frozen.pt")), encoder)
binary.eval()
typer = TypeClassifier("model/type_unsw.pt")

act_fn = (lambda p: choose_action(p)) if args.policy == "cost" else (lambda p: threshold_action(p, args.block_confidence))


def p_attack(canon_row):
    return torch.softmax(binary.infer(canon_row), dim=-1)[1].item()


# --- data: raw rows for the type model, canonical rows for the binary one --
raw = pd.read_csv(args.csv)
# build canonical columns IN PLACE (same transform partition_data applies),
# keeping the raw index so each canonical row pairs with its raw row.
canon = raw.rename(columns={rawc: canonc for canonc, rawc in UNSW_NB15_MAPPING.items()})
canon["proto"] = canon["proto"].map(bucket_proto)
canon["state"] = canon["state"].map(bucket_state)
canon["service"] = canon["service"].astype(str)
canon = synthesize_ip(canon)

attack_idx = raw.index[raw["label"] == 1].tolist()
by_type = collections.defaultdict(list)
for i in attack_idx:
    by_type[str(raw.at[i, "attack_cat"])].append(i)
for t in by_type:
    np.random.shuffle(by_type[t])
pools = {t: itertools.cycle(rows) for t, rows in by_type.items()}
types = sorted(pools)
print(f"streaming held-out UNSW attacks across {len(types)} types: {', '.join(types)}")
print(f"policy={args.policy}  report={'LIVE -> ' + args.device if args.report else 'off (terminal only)'}\n")

comms = None
if args.report:
    if not args.api_base or not args.api_key:
        raise SystemExit("--report needs --api-base/--api-key (or API_BASE_URL/API_KEY env)")
    from edge_agent.comms import CloudComms
    comms = CloudComms(args.api_base, args.api_key, args.device)

seen = collections.Counter()
type_ok = collections.Counter()
n = 0
try:
    for t in itertools.cycle(types):               # round-robin so every type shows fast
        i = next(pools[t])
        canon_row = canon.loc[i]
        raw_row = raw.loc[i]
        p = p_attack(canon_row)
        action = act_fn(p)
        hit = action in ("BLOCK", "ALERT")
        pred_type, type_conf = typer.predict_one(raw_row)
        true_type = str(raw_row["attack_cat"])
        seen[t] += 1
        type_ok[t] += int(pred_type == true_type)
        n += 1
        mark = {"BLOCK": "[BLOCK]", "ALERT": "[ALERT]", "NOOP": "[MISS ]"}[action]
        tcheck = "OK " if pred_type == true_type else "xx "
        print(f"{mark} true={true_type:<14} pred={pred_type:<14}{tcheck} "
              f"P(atk)={p:4.2f} type_conf={type_conf:4.2f}  [{t}: {type_ok[t]}/{seen[t]} typed]")
        if comms is not None:
            comms.report_incident({
                "device_id": args.device,
                "action": action if hit else "MISS",
                "reason": f"held-out {true_type} flow; binary P(attack)={p:.2f}; typed as {pred_type} ({type_conf:.0%})",
                "confidence": round(p, 4),
                "source_ip": canon_row.get("src_ip"),
                "attack_type": pred_type,            # <-- what the dashboard Type column shows
                "attack_type_true": true_type,       # ground truth, for honesty
                "attack_type_confidence": round(float(type_conf), 4),
            })
        if args.limit and n >= args.limit:
            break
        time.sleep(1.0 / args.hz)
except KeyboardInterrupt:
    pass

print("\n=== per-type classification accuracy (this run) ===")
for t in sorted(seen, key=lambda t: -type_ok[t] / max(1, seen[t])):
    print(f"  {t:<14} {type_ok[t]:>4}/{seen[t]:<4} = {type_ok[t]/max(1,seen[t]):5.1%}")
tot_ok, tot = sum(type_ok.values()), sum(seen.values())
print(f"  {'TOTAL':<14} {tot_ok:>4}/{tot:<4} = {tot_ok/max(1,tot):5.1%}")
