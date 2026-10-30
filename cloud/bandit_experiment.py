"""
cloud/bandit_experiment.py

Offline evaluation of the learning agent (edge_agent/bandit.py) on the
ToN_IoT held-out test split -- the only data here with REAL source IPs.

Host-disjoint protocol: ToN_IoT's 47 source IPs are almost perfectly
label-pure (attackers are 192.168.1.30-.37 etc.), so a random FLOW split would
let the bandit memorise hosts. Instead, hosts are split 50/50 (stratified by
majority label, per seed); the bandit learns on train-host flows and is
scored on flows from hosts it never saw. With ~13 attacker hosts this is a
small-sample result -- report it with the seed spread.

Stream: each side's flows are shuffled and arrive every DT simulated
seconds (no timestamps survive partitioning, so per-source history reflects
a host's overall behaviour, not its true timing -- an assumption).

Investigator: SIMULATED, not Claude. A verdict is correct with probability
Q (swept), and one verdict covers a source for COOLDOWN seconds -- the same
reuse the live Investigator's per-IP cooldown gives. Each new verdict costs
INVESTIGATE_COST. Real Claude accuracy has to be measured separately (live).

Policies scored on the test hosts:
  threshold          BLOCK p>=0.9, ALERT p>=0.5 (original rule)
  cost_rule          expected-cost rule (policy.py)
  cost_rule+inv      cost rule, ALERT band -> investigator (current live design)
  bandit_frozen      LinUCB trained on train hosts, greedy, no test updates
  bandit_online      same, keeps learning on test hosts
  bandit_online_disc prior discounted to 500 updates, then learns (= live default)
  bandit_scratch     learns on test hosts from zero (learning curve)
  fed_local_A/B      bandit trained on ONE half of the train hosts
  fed_merged         merge() of A and B (federated)

Usage: python -m cloud.bandit_experiment [seeds...]      (default 0-4)
       python -m cloud.bandit_experiment --prior          train the live prior
"""
import io
import json
import sys

import numpy as np
import pandas as pd
import torch

from edge_agent.bandit import INVESTIGATE_COST, LinUCB, action_cost, context, merge
from edge_agent.flow_history import FlowHistory
from edge_agent.inference import SchemaEncoder
from edge_agent.policy import choose_action, threshold_action
from model.tabular_transformer import load_backbone

DT, WINDOW, COOLDOWN = 0.05, 180.0, 30.0
QS = [0.8, 0.9, 0.95]
encoder = SchemaEncoder("data/processed/vocab.json", "data/processed/scaler.json")
backbone = load_backbone()


def score(df, batch=4096):
    enc = [encoder.encode_row(r) for _, r in df.iterrows()]
    x_cont, x_cat = torch.stack([e[0] for e in enc]), torch.stack([e[1] for e in enc])
    backbone.eval()
    with torch.no_grad():
        return torch.cat([backbone(x_cont[i:i + batch], x_cat[i:i + batch]).softmax(-1)[:, 1]
                          for i in range(0, len(df), batch)]).numpy()


def run(rows, policy, q, rng, bandit=None, learn=False, alpha=0.0, log=None):
    """Replay one stream through one policy. Returns metrics."""
    history, verdicts = FlowHistory(window_s=WINDOW), {}
    tp = fn = fp = tn = blocked_benign = calls = 0
    cost = 0.0
    for i, r in enumerate(rows):
        t, ip, p, y = i * DT, r["src_ip"], r["p"], int(r["label"])
        x = context(history, ip, p, t)
        if policy == "threshold":
            a = threshold_action(p)
        elif policy == "cost_rule":
            a = choose_action(p)
        elif policy == "cost_rule+inv":
            a = choose_action(p)
            a = "INVESTIGATE" if a == "ALERT" else a
        else:
            a = bandit.choose(x, alpha=alpha)
        verdict, new_call = None, False
        if a == "INVESTIGATE":
            cached = verdicts.get(ip)
            if cached and t - cached[0] < COOLDOWN:
                verdict = cached[1]
            else:
                verdict = bool(y) if rng.random() < q else not y
                verdicts[ip], new_call = (t, verdict), True
                calls += 1
        c = action_cost(a, y, verdict) - (INVESTIGATE_COST if a == "INVESTIGATE" and not new_call else 0)
        cost += c
        if learn:
            bandit.update(x, a, -c / 20)
            if log is not None:
                log.append((x, a, -c / 20))
        flagged = a in ("ALERT", "BLOCK") or (a == "INVESTIGATE" and verdict)
        blocked_benign += (not y) and (a == "BLOCK" or (a == "INVESTIGATE" and verdict))
        tp += y and flagged
        fn += y and not flagged
        fp += (not y) and flagged
        tn += (not y) and not flagged
        history.add(r, p, a, t)
    n = len(rows)
    return {"recall": tp / max(tp + fn, 1), "fpr": fp / max(fp + tn, 1),
            "block_fpr": blocked_benign / max(fp + tn, 1),
            "llm_calls_per_1k": 1000 * calls / n, "cost_per_flow": cost / n}


def train(rows, q, rng, log=None):
    bandit = LinUCB(alpha=1.0)
    run(rows, "bandit", q, rng, bandit=bandit, learn=True, alpha=1.0, log=log)
    return bandit


def records(df, rng):
    return df.sample(frac=1.0, random_state=int(rng.integers(1 << 30))).to_dict("records")


if "--prior" in sys.argv:
    # Live prior: one bandit per ToN_IoT device shard (device3, device4),
    # merged -- the federated version of what each device would learn. The
    # backbone saw these rows in pretraining, so its scores here are
    # optimistic; that's fine for a starting prior, not for evaluation.
    rng = np.random.default_rng(0)
    devs = []
    for did in ["device3", "device4"]:
        df = pd.read_csv(f"data/processed/{did}_train.csv")
        df["p"] = score(df)
        devs.append(train(records(df, rng), 0.9, rng))
        print(f"{did}: {devs[-1].n_updates} updates")
    merge(devs).save("model/bandit_prior.npz")
    print("saved model/bandit_prior.npz")
    sys.exit()

ton = pd.read_csv("data/processed/ton_iot_test.csv")
ton["p"] = score(ton)
host_label = ton.groupby("src_ip")["label"].mean().round()
seeds = [int(s) for s in sys.argv[1:]] or [0, 1, 2, 3, 4]
results = []
for seed in seeds:
    rng = np.random.default_rng(seed)
    hosts_train = []
    for lbl in (0.0, 1.0):  # stratified host split
        h = host_label[host_label == lbl].index.to_numpy()
        rng.shuffle(h)
        hosts_train += list(h[: len(h) // 2])
    train_df, test_df = ton[ton.src_ip.isin(hosts_train)], ton[~ton.src_ip.isin(hosts_train)]
    half_a = set(hosts_train[::2])
    train_rows, test_rows = records(train_df, rng), records(test_df, rng)
    rows_a = [r for r in train_rows if r["src_ip"] in half_a]
    rows_b = [r for r in train_rows if r["src_ip"] not in half_a]
    for q in QS:
        res = {"seed": seed, "q": q, "n_test": len(test_rows),
               "test_attack_hosts": int((host_label[~host_label.index.isin(hosts_train)] == 1).sum())}
        for pol in ["threshold", "cost_rule", "cost_rule+inv"]:
            res[pol] = run(test_rows, pol, q, np.random.default_rng(seed))
        central = train(train_rows, q, rng)
        res["bandit_frozen"] = run(test_rows, "bandit", q, np.random.default_rng(seed), bandit=central)
        online = LinUCB(alpha=0.5)
        online.A, online.b = central.A.copy(), central.b.copy()
        res["bandit_online"] = run(test_rows, "bandit", q, np.random.default_rng(seed),
                                   bandit=online, learn=True, alpha=0.5)
        # what run_edge_node.py deploys: the prior discounted to 500 updates
        buf = io.BytesIO()
        central.save(buf)
        buf.seek(0)
        res["bandit_online_disc"] = run(test_rows, "bandit", q, np.random.default_rng(seed),
                                        bandit=LinUCB.load(buf, alpha=0.5, max_weight=500),
                                        learn=True, alpha=0.5)
        res["bandit_scratch"] = run(test_rows, "bandit", q, np.random.default_rng(seed),
                                    bandit=LinUCB(alpha=1.0), learn=True, alpha=1.0)
        log_a, log_b = [], []
        dev_a, dev_b = train(rows_a, q, rng, log_a), train(rows_b, q, rng, log_b)
        fed = merge([dev_a, dev_b])
        # exactness check: refit one bandit on both devices' logged feedback
        refit = LinUCB()
        for x, a, rwd in log_a + log_b:
            refit.update(x, a, rwd)
        res["merge_exact"] = bool(np.allclose(fed.A, refit.A) and np.allclose(fed.b, refit.b))
        for name, bd in [("fed_local_A", dev_a), ("fed_local_B", dev_b), ("fed_merged", fed)]:
            res[name] = run(test_rows, "bandit", q, np.random.default_rng(seed), bandit=bd)
        print("RESULT", json.dumps(res), flush=True)
        results.append(res)

pols = ["threshold", "cost_rule", "cost_rule+inv", "bandit_frozen", "bandit_online",
        "bandit_online_disc", "bandit_scratch", "fed_local_A", "fed_local_B", "fed_merged"]
keys = ["recall", "fpr", "block_fpr", "llm_calls_per_1k", "cost_per_flow"]
print(f"\nmerge exact on every run: {all(r['merge_exact'] for r in results)}")
for q in QS:
    rs = [r for r in results if r["q"] == q]
    print(f"\n=== simulated investigator accuracy q={q}  ({len(rs)} host splits, mean +/- std) ===")
    print(f"{'policy':<16}" + "".join(f"{k:>20}" for k in keys))
    for pol in pols:
        cells = []
        for k in keys:
            v = np.array([r[pol][k] for r in rs])
            cells.append(f"{v.mean():>12.3f} +/- {v.std():<5.3f}")
        print(f"{pol:<16}" + "".join(cells))
