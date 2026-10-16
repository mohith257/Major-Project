"""
cloud/agent_policy_experiment.py

Measures the agentic layer itself -- decision policy, graded response,
analyst feedback, cross-device threat-intel sharing -- by replaying test
flows through the REAL EdgeAgent / DefenseActuator / policy code on a
simulated clock. Only the classifier is precomputed (one batched pass of
the frozen model) and the cloud is an in-memory incident list.

Two streams:
  ton   -- ToN_IoT held-out test split, REAL source IPs (47 IPs, nearly all
           purely benign or purely attack).
  unsw  -- official UNSW-NB15 test set. Its IPs are synthetic per row
           (partition_data.synthesize_ip), so per-IP behaviour is
           meaningless there; we instead group rows into synthetic sessions:
           normal rows over 300 benign hosts, each attack category over 5
           attacker IPs. This grouping is a simulation ASSUMPTION.
Flows are shuffled (seed), arrive every DT simulated seconds, and go to the
4 devices round-robin, so every source IP reaches every device.

Configs (cumulative):
  A threshold_perm   original rule (BLOCK p>=0.9), first block is permanent
  B cost_perm        cost-aware policy, permanent blocks
  C cost_graded      + graded blocks (60 s TTL doubling, permanent at level 4)
  D +feedback        + analyst reviews each BLOCK after REVIEW_DELAY s and
                       rolls back false positives (oracle analyst: an assumption)
  E +sharing         + devices pull peers' BLOCKs every 15 s (full agent)
  D/E_noisyXX        D/E with an imperfect analyst: reviews 50% of BLOCKs,
                       verdict wrong XX% of the time
  *_short            learned exception lasts 5 min instead of 30

Usage: python -m cloud.agent_policy_experiment <ton|unsw> <seed>
Prints "RESULT {...}".
"""
import json
import logging
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import torch

from edge_agent.actuator import DefenseActuator
from edge_agent.agent import EdgeAgent
from edge_agent.comms import active_peer_blocks
from edge_agent.inference import SchemaEncoder
from edge_agent.policy import DEFAULT_COSTS, choose_action, threshold_action
from model.evaluate import _load_test_df, _load_ton_iot_test_df
from model.tabular_transformer import load_backbone

logging.disable(logging.WARNING)  # per-block actuator logs would flood stdout
stream_name, seed = sys.argv[1], int(sys.argv[2])
DT, REVIEW_DELAY, N_DEV = 0.05, 300.0, 4
rng = np.random.default_rng(seed)

df = (_load_ton_iot_test_df() if stream_name == "ton" else _load_test_df()).reset_index(drop=True)
if stream_name == "unsw":
    ips = np.empty(len(df), dtype=object)
    normal = (df["label"] == 0).to_numpy()
    ips[normal] = [f"10.0.{h // 250}.{h % 250 + 1}" for h in rng.integers(0, 300, normal.sum())]
    for k, cat in enumerate(sorted(df.loc[~normal, "attack_cat"].unique())):
        m = (df["attack_cat"] == cat).to_numpy() & ~normal
        ips[m] = [f"172.16.{k}.{a + 1}" for a in rng.integers(0, 5, m.sum())]
    df["src_ip"] = ips
df = df.sample(frac=1.0, random_state=seed).reset_index(drop=True)
labels = df["label"].astype(int).to_numpy()

# one batched pass of the frozen classifier
enc = SchemaEncoder("data/processed/vocab.json", "data/processed/scaler.json")
model = load_backbone().eval()
encoded = [enc.encode_row(r) for _, r in df.iterrows()]
xc, xk = torch.stack([e[0] for e in encoded]), torch.stack([e[1] for e in encoded])
with torch.no_grad():
    logits = torch.cat([model(xc[i:i + 8192], xk[i:i + 8192]) for i in range(0, len(df), 8192)])
p_attack = logits.softmax(-1)[:, 1].numpy()


# ---- per-flow decision quality: threshold rule vs cost-aware rule ----------
def flow_metrics(actions):
    a, y = np.array(actions), labels
    return {"false_block_rate": float((a[y == 0] == "BLOCK").mean()),
            "benign_alert_rate": float((a[y == 0] == "ALERT").mean()),
            "attack_block_rate": float((a[y == 1] == "BLOCK").mean()),
            "attack_miss_rate": float((a[y == 1] == "NOOP").mean())}


def total_cost(actions, costs):
    return float(sum(costs[a][y] for a, y in zip(actions, labels)) / len(labels))


cost_tables = {
    "default": DEFAULT_COSTS,
    "block_cheap": {"NOOP": (0, 10), "ALERT": (1, 3), "BLOCK": (5, 0)},
    "miss_cheap": {"NOOP": (0, 3), "ALERT": (1, 2), "BLOCK": (20, 0)},
}
per_flow = {}
thr = [threshold_action(p) for p in p_attack]
for name, table in cost_tables.items():
    pol = [choose_action(p, table) for p in p_attack]
    per_flow[name] = {"threshold": {**flow_metrics(thr), "cost_per_flow": total_cost(thr, table)},
                      "cost_policy": {**flow_metrics(pol), "cost_per_flow": total_cost(pol, table)}}


# ---- stream simulation with the real agent --------------------------------
class _PrecomputedModel:
    """infer() returns the precomputed logits carried on the record. No
    `encoder`/`model` attributes, so EdgeAgent._explain() returns None."""
    def infer(self, rec):
        return rec.logits


class _MemoryCloud:
    def __init__(self):
        self.incidents = []


class _Comms:
    def __init__(self, cloud, device_id):
        self.cloud, self.device_id, self.now = cloud, device_id, 0.0

    def fetch_peer_blocks(self):
        return active_peer_blocks(self.cloud.incidents, self.device_id)

    def fetch_global_adapter(self):
        return None

    def upload_adapter(self, *a, **k):
        return None


def simulate(policy, graded, feedback, sharing, review_frac=1.0, analyst_err=0.0, exception_ttl=1800):
    # review_frac: share of BLOCKs the analyst ever looks at; analyst_err: chance a
    # reviewed verdict is wrong (benign confirmed, or an attack rolled back).
    rev_rng = np.random.default_rng(seed + 1)
    cloud = _MemoryCloud()
    agents, comms = [], []
    for d in range(N_DEV):
        c = _Comms(cloud, f"device{d + 1}")
        act = DefenseActuator(simulate=True, base_ttl=60.0, permanent_after=4 if graded else 1)
        ag = EdgeAgent(device_id=c.device_id, model=_PrecomputedModel(),
                       drift_monitor=SimpleNamespace(update=lambda c: None, is_drifting=lambda: False, window=[]),
                       self_eval_trigger=None, trainer=None, actuator=act, comms=c,
                       sync_poll_interval=15, self_eval_interval=float("inf"),
                       policy=policy, gate_updates=False, share_intel=sharing,
                       exception_ttl=exception_ttl)
        act.incident_sink = (lambda e, c=c: cloud.incidents.append({**e, "timestamp": c.now}))
        agents.append(ag)
        comms.append(c)
    reviews = []  # (due_time, device_index, ip, was_false_positive)
    benign_dropped = attack_dropped = attack_blocked = attack_admitted = 0
    benign_ips_blocked = set()
    rollbacks = 0
    admitted_after_known = 0  # attack flows admitted from an IP some device had already blocked
    first_block_time = {}
    for i in range(len(df)):
        now = i * DT
        d = i % N_DEV
        ag, ip, y = agents[d], df.at[i, "src_ip"], labels[i]
        comms[d].now = now
        while reviews and reviews[0][0] <= now:
            _, dd, rip, fp = reviews.pop(0)
            agents[dd].feedback(rip, "BLOCK", fp, now=now)
            rollbacks += fp
        ag.actuator.expire(now)
        if ag.actuator.is_blocked(ip, now):
            benign_dropped += y == 0
            attack_dropped += y == 1
            continue
        rec = SimpleNamespace(logits=logits[i], src_ip=ip)
        decision, _, _ = ag.run_step(rec, now=now)
        if decision.action.name == "BLOCK":
            first_block_time.setdefault(ip, now)
            if y == 0:
                benign_ips_blocked.add(ip)
            else:
                attack_blocked += 1
            if feedback and rev_rng.random() < review_frac:
                reviews.append((now + REVIEW_DELAY, d, ip, bool(y == 0) != (rev_rng.random() < analyst_err)))
        elif y == 1:
            attack_admitted += 1
            admitted_after_known += ip in first_block_time
    n_benign, n_attack = int((labels == 0).sum()), int((labels == 1).sum())
    return {"benign_flows_dropped_pct": 100 * benign_dropped / n_benign,
            "benign_ips_ever_blocked": len(benign_ips_blocked),
            "attack_flows_stopped_pct": 100 * (attack_dropped + attack_blocked) / n_attack,
            "attack_flows_admitted_pct": 100 * attack_admitted / n_attack,
            "attack_admitted_after_ip_known_pct": 100 * admitted_after_known / n_attack,
            "rollbacks": int(rollbacks),
            "final_block_cost": [round(ag.costs["BLOCK"][0], 2) for ag in agents]}


configs = {
    "A_threshold_perm": ("threshold", False, False, False),
    "B_cost_perm": ("cost", False, False, False),
    "C_cost_graded": ("cost", True, False, False),
    "D_graded_feedback": ("cost", True, True, False),
    "E_full_sharing": ("cost", True, True, True),
    # imperfect analyst: reviews half the blocks, wrong 10% / 20% of the time
    "D_noisy10": ("cost", True, True, False, 0.5, 0.1),
    "E_noisy10": ("cost", True, True, True, 0.5, 0.1),
    "E_noisy20": ("cost", True, True, True, 0.5, 0.2),
    # shorter learned exception (5 min instead of 30): limits what one wrong rollback costs
    "E_short": ("cost", True, True, True, 1.0, 0.0, 300),
    "E_noisy10_short": ("cost", True, True, True, 0.5, 0.1, 300),
    "E_noisy20_short": ("cost", True, True, True, 0.5, 0.2, 300),
}
stream = {name: simulate(*cfg) for name, cfg in configs.items()}
print("RESULT " + json.dumps({"stream": stream_name, "seed": seed, "n_flows": len(df),
                              "n_src_ips": int(df["src_ip"].nunique()),
                              "per_flow": per_flow, "simulation": stream}))
