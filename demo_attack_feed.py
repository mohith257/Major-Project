"""
demo_attack_feed.py -- stream real held-out attacks through the live model.

Shows actual attacks "taking place": it replays labelled flows the model never
trained on (ToN-IoT test set + the Fuzzers hold-out), classifies each with the
SAME InferenceModel + policy a real node runs, and prints a streaming verdict
plus a per-class scoreboard. Classes interleave so every attack type shows fast.

  python demo_attack_feed.py                 # terminal scoreboard only
  python demo_attack_feed.py --report        # ALSO push to the live dashboard
  python demo_attack_feed.py --fuzzers --hz 5 --policy threshold

Honesty line for the viva: these are REAL held-out attack flows (not live wire,
not fabricated), scored by the production binary detector. The attack *name*
(ddos/ransomware/...) is the dataset's ground-truth label -- the model only
outputs P(attack); the policy turns that into BLOCK/ALERT/NOOP. With --report
they appear under device_id "replay-demo" so they never masquerade as a real
node's internet detections.

Run from the repo root (expects data/processed/ and model/backbone_frozen.pt).
"""
import argparse
import collections
import copy
import itertools
import os
import time

import pandas as pd
import torch

from edge_agent.inference import InferenceModel, SchemaEncoder
from edge_agent.policy import choose_action, threshold_action
from model.tabular_transformer import load_backbone, wrap_with_lora

ap = argparse.ArgumentParser()
ap.add_argument("--csv", default="data/processed/ton_iot_test.csv")
ap.add_argument("--fuzzers", action="store_true", help="also stream the Fuzzers hold-out (the blind spot)")
ap.add_argument("--hz", type=float, default=3.0, help="flows per second")
ap.add_argument("--policy", choices=["cost", "threshold"], default="cost")
ap.add_argument("--block-confidence", type=float, default=0.65)
ap.add_argument("--limit", type=int, default=0, help="stop after N flows (0 = run until Ctrl-C)")
ap.add_argument("--report", action="store_true", help="POST each verdict to the live API")
ap.add_argument("--api-base", default=os.environ.get("API_BASE_URL"))
ap.add_argument("--api-key", default=os.environ.get("API_KEY"))
ap.add_argument("--device", default="replay-demo")
args = ap.parse_args()

encoder = SchemaEncoder("data/processed/vocab.json", "data/processed/scaler.json")
model = InferenceModel(wrap_with_lora(load_backbone("model/backbone_frozen.pt")), encoder)
model.eval()

act_fn = (lambda p: choose_action(p)) if args.policy == "cost" else (lambda p: threshold_action(p, args.block_confidence))


def p_attack(row):
    return torch.softmax(model.infer(row), dim=-1)[1].item()


# Build a class-balanced, interleaved attack stream so every type shows quickly.
frames = [pd.read_csv(args.csv)]
if args.fuzzers:
    frames.append(pd.read_csv("data/processed/holdout_replay.csv"))
df = pd.concat(frames, ignore_index=True)
attacks = df[df["label"] == 1].copy()
attacks["cat"] = attacks["attack_cat"].str.lower()
by_cat = {c: g.sample(frac=1.0).to_dict("records") for c, g in attacks.groupby("cat")}
pools = {c: itertools.cycle(rows) for c, rows in by_cat.items()}
cats = sorted(pools)
print(f"streaming {len(attacks)} held-out attack flows across {len(cats)} classes: {', '.join(cats)}")
print(f"policy={args.policy}  report={'LIVE -> ' + args.device if args.report else 'off (terminal only)'}\n")

comms = None
if args.report:
    if not args.api_base or not args.api_key:
        raise SystemExit("--report needs --api-base/--api-key (or API_BASE_URL/API_KEY env)")
    from edge_agent.comms import CloudComms
    comms = CloudComms(args.api_base, args.api_key, args.device)

seen = collections.Counter()
caught = collections.Counter()
n = 0
try:
    for cat in itertools.cycle(cats):              # round-robin: ddos, dos, injection, ...
        row = next(pools[cat])
        p = p_attack(row)
        action = act_fn(p)
        hit = action in ("BLOCK", "ALERT")
        seen[cat] += 1
        caught[cat] += int(hit)
        n += 1
        mark = {"BLOCK": "[BLOCK]", "ALERT": "[ALERT]", "NOOP": "[MISS ]"}[action]
        print(f"{mark} {cat:<12} {str(row.get('src_ip','')):<16} P(attack)={p:5.2f}  "
              f"[{cat}: {caught[cat]}/{seen[cat]} caught]")
        if comms is not None:
            comms.report_incident({
                "device_id": args.device,
                "action": action if hit else "MISS",
                "reason": f"held-out {cat} flow replayed (unseen); P(attack)={p:.2f}",
                "confidence": round(p, 4),
                "source_ip": row.get("src_ip"),
            })
        if args.limit and n >= args.limit:
            break
        time.sleep(1.0 / args.hz)
except KeyboardInterrupt:
    pass

print("\n=== per-class detection (this run) ===")
for c in sorted(seen, key=lambda c: -caught[c] / seen[c]):
    print(f"  {c:<12} {caught[c]:>4}/{seen[c]:<4} = {caught[c]/seen[c]:5.1%}")
print(f"  {'TOTAL':<12} {sum(caught.values()):>4}/{sum(seen.values()):<4} = {sum(caught.values())/max(1,sum(seen.values())):5.1%}")
