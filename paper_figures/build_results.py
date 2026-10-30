"""
paper_figures/build_results.py

Turns the raw AWS node logs (copied into paper_figures/aws_logs/*.txt) into
  - paper_figures/results_final.json   every parsed run, plus aggregates
  - paper_figures/results_tables.tex   LaTeX tables (booktabs), mean +- sample sd
  - paper_figures/fig8_ablation.png, fig9_agent.png
Every number comes from a "RESULT {...}" or "MULTI ..." line printed on an EC2 node.

Run: python paper_figures/build_results.py
"""
import glob
import json
import statistics as st
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = "paper_figures"
results, multi, multi_v2, evals, refs = [], defaultdict(dict), defaultdict(dict), [], defaultdict(list)
for path in sorted(glob.glob(f"{OUT}/aws_logs/*.txt")):
    for line in open(path, encoding="utf-8", errors="replace"):
        if line.startswith("RESULT "):
            results.append(json.loads(line[7:]))
        elif line.startswith(("RESULT_BASELINE ", "RESULT_GBM ", "RESULT_CURVE ")):
            tag, body = line.split(" ", 1)
            refs[tag].append(json.loads(body))
        elif line.startswith("RESULT_EVAL "):
            evals.append(json.loads(line[12:]))
        elif line.startswith(("MULTI ", "MULTIV2 ")):
            parts = line.split()
            if len(parts) == 8 and parts[2].isdigit():
                seed, rnd = int(parts[1]), int(parts[2])
                (multi_v2 if parts[0] == "MULTIV2" else multi)[seed][rnd] = dict(
                    zip(["fuzzers", "replay", "acc", "fpr"], map(float, parts[4:8])))

# exp10 re-ran some (variant, seed) / (stream, seed) jobs with extra fields
# (operating point, imperfect analyst). Keep one run per key: the richest.
def _key(r):
    return ("abl", r["variant"], r["seed"]) if "variant" in r else ("agent", r["stream"], r["seed"])


def _richness(r):
    return len(r["rounds"][-1]) if "variant" in r else len(r["simulation"])


best = {}
for r in results:
    if _key(r) not in best or _richness(r) > _richness(best[_key(r)]):
        best[_key(r)] = r
results = list(best.values())
for tag in refs:  # one run per seed (curves: one per model)
    refs[tag] = list({r.get("seed", r.get("model")): r for r in refs[tag]}.values())


def ms(vals, scale=100.0, nd=2):
    vals = [v * scale for v in vals]
    if len(vals) == 1:
        return f"{vals[0]:.{nd}f}"
    return f"{st.mean(vals):.{nd}f} $\\pm$ {st.stdev(vals):.{nd}f}"


def agg(vals):
    return {"mean": st.mean(vals), "sd": st.stdev(vals) if len(vals) > 1 else 0.0, "n": len(vals)}


tex, summary = [], {}

# ---- Table: backbone v1 vs v2 (v2 trained + evaluated on EC2) -------------------
if evals:
    ev = [e["r"] for e in evals]
    summary["backbone_v2"] = {
        "n": len(ev),
        "unsw_acc": agg([e["unsw"]["accuracy"] for e in ev]), "unsw_fpr": agg([e["unsw"]["false_positive_rate"] for e in ev]),
        "unsw_f1": agg([e["unsw"]["macro_f1"] for e in ev]), "fuzzers": agg([e["fuzzers_recall"] for e in ev]),
        "ton_acc": agg([e["ton_iot"]["accuracy"] for e in ev]), "ton_fpr": agg([e["ton_iot"]["false_positive_rate"] for e in ev]),
        "ton_f1": agg([e["ton_iot"]["macro_f1"] for e in ev]),
        "latency_median_ms": agg([e["latency"]["median_ms"] for e in ev]), "latency_p95_ms": agg([e["latency"]["p95_ms"] for e in ev]),
        "payload_bytes": ev[0]["payload"]["adapter_json_bytes"],
        "confusion_unsw": [e["unsw"]["confusion_matrix"] for e in ev],
    }
    rows_v2 = [
        ("UNSW accuracy (\\%)", "87.19", ms([e["unsw"]["accuracy"] for e in ev])),
        ("UNSW macro-F1", "0.871", ms([e["unsw"]["macro_f1"] for e in ev], 1, 3)),
        ("UNSW FPR (\\%)", "14.31", ms([e["unsw"]["false_positive_rate"] for e in ev])),
        ("Fuzzers recall (\\%)", "41.06", ms([e["fuzzers_recall"] for e in ev])),
        ("ToN\\_IoT accuracy (\\%)", "98.84", ms([e["ton_iot"]["accuracy"] for e in ev])),
        ("ToN\\_IoT FPR (\\%)", "1.93", ms([e["ton_iot"]["false_positive_rate"] for e in ev])),
        ("Median latency (ms, t3.small)", "1.71", ms([e["latency"]["median_ms"] for e in ev], 1)),
    ]
    tex += [r"\begin{table}[t]\centering",
            r"\caption{Frozen backbone before federation: official UNSW-NB15 test set (82{,}332 flows) and ToN\_IoT "
            r"held-out split (31{,}656 flows). v1: one token for all continuous features, 10 epochs, single run. "
            rf"v2: one token per feature, 30 epochs, one-cycle LR, mean $\pm$ sd over {len(ev)} seeds. Trained and evaluated on EC2.}}",
            r"\label{tab:backbone}",
            r"\begin{tabular}{lcc}\toprule",
            r"Metric & v1 & v2 \\ \midrule"]
    tex += [f"{a} & {b} & {c} \\\\" for a, b, c in rows_v2]
    tex += [r"\bottomrule\end{tabular}\end{table}", ""]

# ---- Table: federated Fuzzers progression (Lambda code path, moto) -------------
for tag, mr in (("v1", multi), ("v2", multi_v2)):
    if not mr:
        continue
    seeds = sorted(mr)
    rows = []
    for rnd in range(5):
        have = [mr[s][rnd] for s in seeds if rnd in mr[s]]
        rows.append((rnd, have))
        summary[f"multiround_{tag}_round{rnd}"] = {k: agg([h[k] for h in have]) for k in ("fuzzers", "replay", "acc", "fpr")}
    tex += [r"\begin{table}[t]\centering",
            rf"\caption{{Global model after each FedAvg round, backbone {tag} (mean $\pm$ sd over {len(seeds)} seeds; "
            r"real Lambda handler code on EC2 t3.small with DynamoDB/S3 mocked).}",
            rf"\label{{tab:fed_rounds_{tag}}}",
            r"\begin{tabular}{ccccc}\toprule",
            r"Round & Fuzzers recall (\%) & Replay acc. (\%) & UNSW acc. (\%) & UNSW FPR (\%) \\ \midrule"]
    for rnd, have in rows:
        tex.append(f"{rnd} & {ms([h['fuzzers'] for h in have])} & {ms([h['replay'] for h in have])} & "
                   f"{ms([h['acc'] for h in have])} & {ms([h['fpr'] for h in have])} \\\\")
    tex += [r"\bottomrule\end{tabular}\end{table}", ""]

# ---- Table: ablations / gate / poisoning / FedProx ------------------------------
abl = defaultdict(list)
for r in results:
    if "variant" in r:
        abl[r["variant"]].append(r)
order = ["lora_r1", "lora_r2", "lora_r4", "lora_r8", "full", "no_mining", "no_adv", "fedprox",
         "median", "gated", "poison", "poison_gated", "poison_median", "spread2", "spread3", "long", "spread3_long"]
label = {"lora_r1": "LoRA $r{=}1$", "lora_r2": "LoRA $r{=}2$", "lora_r4": "LoRA $r{=}4$ (default)",
         "lora_r8": "LoRA $r{=}8$", "full": "Full-model FedAvg", "no_mining": "w/o hard-example mining",
         "no_adv": "w/o FGSM training", "fedprox": "FedProx ($\\mu{=}0.01$)", "gated": "+ adoption gate",
         "poison": "Poisoned client, FedAvg", "poison_gated": "Poisoned client, FedAvg + gate",
         "median": "Median aggregation", "poison_median": "Poisoned client, median",
         "spread2": "Fuzzers on 2 clients", "spread3": "Fuzzers on 3 clients",
         "long": r"5$\times$ local steps", "spread3_long": r"3 clients + 5$\times$ steps"}
if abl:
    tex += [r"\begin{table*}[t]\centering",
            r"\caption{Ablations after 4 federated rounds, global model on device 2 (mean $\pm$ sd over 3 seeds; EC2). "
            r"Payload = raw float32 bytes uploaded per device per round. Adv.\ acc.\ = accuracy under FGSM, $\epsilon{=}0.05$, 5{,}000 test flows.}",
            r"\label{tab:ablation}",
            r"\begin{tabular}{lrcccccc}\toprule",
            r"Variant & Payload (B) & Fuzzers rec. (\%) & UNSW acc. (\%) & UNSW FPR (\%) & Macro-F1 & Adv. acc. (\%) & ToN acc. (\%) \\ \midrule"]
    for v in order:
        rs = abl.get(v)
        if not rs:
            continue
        last = [r["rounds"][-1] for r in rs]
        summary[f"ablation_{v}"] = {
            "n": len(rs), "payload_bytes": rs[0]["payload_bytes"],
            "fuzzers": agg([x["fuzzers_recall"] for x in last]), "acc": agg([x["acc"] for x in last]),
            "fpr": agg([x["fpr"] for x in last]), "macro_f1": agg([x["macro_f1"] for x in last]),
            "fgsm_clean": agg([r["fgsm_clean_acc"] for r in rs]), "fgsm_adv": agg([r["fgsm_adv_acc"] for r in rs]),
            "ton_acc": agg([r["ton_acc"] for r in rs]),
            "acceptance": [[x.get("accepted") for x in r["rounds"][1:]] for r in rs],
        }
        tex.append(f"{label[v]} & {rs[0]['payload_bytes']:,} & {ms([x['fuzzers_recall'] for x in last])} & "
                   f"{ms([x['acc'] for x in last])} & {ms([x['fpr'] for x in last])} & "
                   f"{ms([x['macro_f1'] for x in last], 1, 3)} & {ms([r['fgsm_adv_acc'] for r in rs])} & "
                   f"{ms([r['ton_acc'] for r in rs])} \\\\")
    tex += [r"\bottomrule\end{tabular}\end{table*}", ""]

# ---- Tables: decision policy + agent stream simulation --------------------------
agent = defaultdict(list)
for r in results:
    if "stream" in r:
        agent[r["stream"]].append(r)
cfg_label = {"A_threshold_perm": "A: threshold rule, permanent block",
             "B_cost_perm": "B: cost-aware, permanent block",
             "C_cost_graded": "C: + graded blocks (TTL)",
             "D_graded_feedback": "D: + analyst rollback \\& exceptions",
             "E_full_sharing": "E: + peer intel w/ retraction (full)"}
for stream, rs in sorted(agent.items()):
    name = "ToN\\_IoT (real IPs)" if stream == "ton" else "UNSW-NB15 (synthetic sessions)"
    pf = {pol: {k: [r["per_flow"]["default"][pol][k] for r in rs] for k in rs[0]["per_flow"]["default"][pol]}
          for pol in ("threshold", "cost_policy")}
    summary[f"policy_{stream}"] = {pol: {k: agg(v) for k, v in d.items()} for pol, d in pf.items()}
    tex += [r"\begin{table}[t]\centering",
            rf"\caption{{Per-flow decisions, {name}, default cost table (frozen model).}}",
            rf"\label{{tab:policy_{stream}}}",
            r"\begin{tabular}{lcccc}\toprule",
            r"Policy & False block (\%) & Benign alert (\%) & Attack missed (\%) & Cost/flow \\ \midrule"]
    for pol, lab in (("threshold", "Threshold ($p\\geq0.9$)"), ("cost_policy", "Cost-aware (Bayes)")):
        d = pf[pol]
        tex.append(f"{lab} & {ms(d['false_block_rate'])} & {ms(d['benign_alert_rate'])} & "
                   f"{ms(d['attack_miss_rate'])} & {ms(d['cost_per_flow'], 1, 3)} \\\\")
    tex += [r"\bottomrule\end{tabular}\end{table}", ""]

    sims = {c: {k: [r["simulation"][c][k] for r in rs] for k in
                ("benign_flows_dropped_pct", "attack_flows_admitted_pct", "attack_admitted_after_ip_known_pct",
                 "benign_ips_ever_blocked", "rollbacks")} for c in cfg_label}
    summary[f"agent_{stream}"] = {c: {k: agg(v) for k, v in d.items()} for c, d in sims.items()}
    tex += [r"\begin{table}[t]\centering",
            rf"\caption{{Four-agent stream simulation, {name} ({len(rs)} seeds). Dropped = benign flows refused by an active block; "
            r"unblocked = attack flows not blocked or dropped.}",
            rf"\label{{tab:agent_{stream}}}",
            r"\begin{tabular}{lccc}\toprule",
            r"Agent configuration & Benign dropped (\%) & Attack unblocked (\%) & Rollbacks \\ \midrule"]
    for c, lab in cfg_label.items():
        d = sims[c]
        tex.append(f"{lab} & {ms(d['benign_flows_dropped_pct'], 1)} & {ms(d['attack_flows_admitted_pct'], 1, 3)} & "
                   f"{ms(d['rollbacks'], 1, 0)} \\\\")
    tex += [r"\bottomrule\end{tabular}\end{table}", ""]

# ---- Table: threshold-free view of federation (exp10 runs carry these fields) ----
op_keys = ("auroc", "fuzzers_auroc", "fuzzers_recall_at_fpr10")
op_vs = [v for v in ("lora_r4", "lora_r8", "full", "median", "spread2", "spread3", "long", "spread3_long") if any("auroc" in r["rounds"][-1] for r in abl.get(v, []))]
if op_vs:
    tex += [r"\begin{table}[t]\centering",
            r"\caption{Threshold-free view of federation (official UNSW-NB15 test set, 3 seeds; EC2). AUROC over all flows, "
            r"Fuzzers-vs-benign AUROC, and Fuzzers recall at a fixed 10\% benign FPR (threshold set on the benign test flows), "
            r"before (round 0) and after (round 4) federation.}",
            r"\label{tab:operating}",
            r"\begin{tabular}{llccc}\toprule",
            r"Variant & Round & AUROC & Fuzzers AUROC & Fuzzers rec.\ @10\% FPR (\%) \\ \midrule"]
    for v in op_vs:
        rs = [r for r in abl[v] if "auroc" in r["rounds"][-1]]
        for rnd in (0, 4):
            pts = [r["rounds"][rnd] for r in rs]
            summary[f"operating_{v}_round{rnd}"] = {k: agg([p[k] for p in pts]) for k in op_keys}
            tex.append(f"{label[v] if rnd == 0 else ''} & {rnd} & {ms([p['auroc'] for p in pts], 1, 3)} & "
                       f"{ms([p['fuzzers_auroc'] for p in pts], 1, 3)} & {ms([p['fuzzers_recall_at_fpr10'] for p in pts])} \\\\")
    tex += [r"\bottomrule\end{tabular}\end{table}", ""]

# ---- Table: federation vs. only moving the frozen backbone's threshold ----------
curve = {c["model"]: c for c in refs.get("RESULT_CURVE", [])}
if "backbone" in curve and abl:
    pairs = [("LoRA $r{=}4$, 4 rounds", "0.183", [r["rounds"][-1] for r in abl["lora_r4"]]),
             ("LoRA $r{=}8$, 4 rounds", "0.212", [r["rounds"][-1] for r in abl["lora_r8"]]),
             ("Full-model FedAvg, 4 rounds", "0.331", [r["rounds"][-1] for r in abl["full"]])]
    # exp11: more Fuzzers clients / longer local training (curve points match their mean FPR)
    pairs += [(f"{label[v]}, 4 rounds", key, [r["rounds"][-1] for r in abl[v]])
              for v, key in (("spread2", "0.185"), ("long", "0.282"), ("spread3", "0.336"), ("spread3_long", "0.374"))
              if v in abl and key in curve["backbone"]["curve"]]
    if multi:
        pairs.insert(1, ("LoRA $r{=}4$, Lambda path (4 seeds)", "0.192",
                         [{"fpr": multi[s_][4]["fpr"], "fuzzers_recall": multi[s_][4]["fuzzers"]} for s_ in multi]))
    summary["threshold_only"] = {"backbone": curve["backbone"], "centralized": curve.get("model/baseline_centralized.pt")}
    tex += [r"\begin{table}[t]\centering",
            r"\caption{Federated Fuzzers recall vs.\ the frozen backbone with only its decision threshold moved to the same "
            r"benign FPR (official UNSW-NB15 test set; EC2). The frozen model needs no federation at all.}",
            r"\label{tab:threshold}",
            r"\begin{tabular}{lccc}\toprule",
            r"Federated model & FPR (\%) & Fuzzers rec.\ (\%) & Frozen, threshold moved (\%) \\ \midrule"]
    for lab, key, pts in pairs:
        tex.append(f"{lab} & {ms([p['fpr'] for p in pts])} & {ms([p['fuzzers_recall'] for p in pts])} & "
                   f"{100 * curve['backbone']['curve'][key]['fuzzers_recall']:.2f} \\\\")
    tex += [r"\bottomrule\end{tabular}\end{table}", ""]

# ---- Table: imperfect analyst / exception length (exp10 agent runs) ------------
an_label = {"C_cost_graded": "C: no analyst", "E_full_sharing": "E: oracle analyst, 30-min exception",
            "E_noisy10": "E: 50\\% reviewed, 10\\% wrong", "E_noisy20": "E: 50\\% reviewed, 20\\% wrong",
            "E_short": "E: oracle, 5-min exception", "E_noisy10_short": "E: 10\\% wrong, 5-min exception",
            "E_noisy20_short": "E: 20\\% wrong, 5-min exception"}
if all(any(c in r["simulation"] for r in agent[s_]) for s_ in agent for c in an_label):
    tex += [r"\begin{table*}[t]\centering",
            r"\caption{Sensitivity of the full agent to the analyst (3 seeds; EC2). The analyst reviews a random 50\% of blocks "
            r"and gives the wrong verdict with the stated probability; a wrong verdict on an attacker rolls its block back "
            r"and grants it the learned exception.}",
            r"\label{tab:analyst}",
            r"\begin{tabular}{lcccc}\toprule",
            r" & \multicolumn{2}{c}{ToN\_IoT} & \multicolumn{2}{c}{UNSW-NB15} \\",
            r"Configuration & Benign dropped (\%) & Attack unblocked (\%) & Benign dropped (\%) & Attack unblocked (\%) \\ \midrule"]
    for c, lab in an_label.items():
        cells = []
        for s_ in ("ton", "unsw"):
            rs = [r for r in agent[s_] if c in r["simulation"]]
            b = [r["simulation"][c]["benign_flows_dropped_pct"] for r in rs]
            a = [r["simulation"][c]["attack_flows_admitted_pct"] for r in rs]
            summary[f"analyst_{s_}_{c}"] = {"benign_dropped": agg(b), "attack_unblocked": agg(a)}
            cells += [ms(b, 1), ms(a, 1, 3)]
        tex.append(f"{lab} & " + " & ".join(cells) + r" \\")
    tex += [r"\bottomrule\end{tabular}\end{table*}", ""]

# ---- Table: reference models (centralized Transformer, gradient-boosted trees) --
if refs:
    rows = []
    for tag, lab, note in (("RESULT_GBM", "Gradient-boosted trees", "pretraining pool, Fuzzers excluded"),
                           ("RESULT_BASELINE", "Centralized Transformer", "all device data incl.\\ Fuzzers")):
        rs = refs.get(tag)
        if not rs:
            continue
        summary[f"ref_{tag}"] = {"n": len(rs), "acc": agg([r["unsw"]["accuracy"] for r in rs]),
                                 "fpr": agg([r["unsw"]["false_positive_rate"] for r in rs]),
                                 "fuzzers": agg([r["fuzzers_recall"] for r in rs]),
                                 "ton_acc": agg([r["ton_iot"]["accuracy"] for r in rs])}
        rows.append(f"{lab} ({note}) & {ms([r['unsw']['accuracy'] for r in rs])} & "
                    f"{ms([r['unsw']['false_positive_rate'] for r in rs])} & {ms([r['fuzzers_recall'] for r in rs])} & "
                    f"{ms([r['ton_iot']['accuracy'] for r in rs])} \\\\")
    tex += [r"\begin{table*}[t]\centering",
            r"\caption{Reference models on the same test sets and eight features (3 seeds each; trained and evaluated on EC2). "
            r"Neither is federated; they bound what the frozen backbone and the federated system are compared against.}",
            r"\label{tab:refs}",
            r"\begin{tabular}{lcccc}\toprule",
            r"Model (training data) & UNSW acc. (\%) & UNSW FPR (\%) & Fuzzers rec. (\%) & ToN acc. (\%) \\ \midrule",
            *rows,
            r"Backbone v1, frozen (pretraining pool) & 87.19 & 14.31 & 41.06 & 98.84 \\",
            f"Backbone v1 + 4 LoRA rounds (federated) & {ms([multi[s_][4]['acc'] for s_ in multi])} & "
            f"{ms([multi[s_][4]['fpr'] for s_ in multi])} & {ms([multi[s_][4]['fuzzers'] for s_ in multi])} & -- \\\\",
            r"\bottomrule\end{tabular}\end{table*}", ""]

open(f"{OUT}/results_tables.tex", "w").write("\n".join(tex))
json.dump({"summary": summary, "runs": results, "multiround_v1": multi, "multiround_v2": multi_v2, "evals": evals}, open(f"{OUT}/results_final.json", "w"), indent=1)

# ---- figures: Fig 2 (line), Fig 3 and Fig 4 (bars). Fig 1 = architecture --------
import numpy as np  # noqa: E402

def mean_sd(vals):
    return 100 * st.mean(vals), (100 * st.stdev(vals) if len(vals) > 1 else 0.0)

if multi or multi_v2:
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.4))
    for tag, mr, style in (("backbone v1", multi, "-"), ("backbone v2", multi_v2, "--")):
        if not mr:
            continue
        for ax, key, name in ((axes[0], "fuzzers", "Fuzzers recall (%)"), (axes[1], "fpr", "UNSW FPR (%)")):
            m = [mean_sd([mr[sd][r][key] for sd in mr if r in mr[sd]]) for r in range(5)]
            ax.errorbar(range(5), [a for a, _ in m], yerr=[b for _, b in m], fmt="o" + style, capsize=3, label=tag)
            ax.set_xlabel("federated round")
            ax.set_ylabel(name)
            ax.set_xticks(range(5))
    axes[0].legend()
    fig.suptitle("Global model after each FedAvg round (EC2, mean $\\pm$ sd)")
    fig.tight_layout()
    fig.savefig(f"{OUT}/fig2_rounds.png", dpi=200)

if abl:
    # poisoning variants are reported in the table only (their FPR swings 0-100% would swamp the axis)
    vs = [v for v in order if v in abl and not v.startswith("poison")]
    metrics = (("fuzzers", "Fuzzers recall"), ("fpr", "UNSW FPR"), ("fgsm_adv", "FGSM accuracy"))
    x = np.arange(len(vs))
    w = 0.27
    fig, ax = plt.subplots(figsize=(10, 4.4))
    for k, (key, name) in enumerate(metrics):
        mu = [100 * summary[f"ablation_{v}"][key]["mean"] for v in vs]
        sd = [100 * summary[f"ablation_{v}"][key]["sd"] for v in vs]
        ax.bar(x + (k - 1) * w, mu, w, yerr=sd, capsize=2, label=name)
    ticks = [label[v].replace("$", "").replace("{=}", "=").replace(" (default)", "*").replace("\\mu", "mu").replace("\\times", "x")
             + "\n" + f"{summary[f'ablation_{v}']['payload_bytes'] / 1024:.1f} KB" for v in vs]
    ax.set_xticks(x)
    ax.set_xticklabels(ticks, fontsize=8, rotation=30, ha="right")
    ax.set_ylabel("%")
    ax.legend(ncol=3, fontsize=8)
    ax.set_title("Ablations after 4 rounds (EC2, 3 seeds; KB = upload per device per round)")
    fig.tight_layout()
    fig.savefig(f"{OUT}/fig3_ablation_bars.png", dpi=200)

if agent:
    fig, axes = plt.subplots(1, len(agent), figsize=(5.5 * len(agent), 3.6), squeeze=False)
    for ax, (stream, rs) in zip(axes[0], sorted(agent.items())):
        s = summary[f"agent_{stream}"]
        x = np.arange(len(cfg_label))
        b1 = ax.bar(x - 0.2, [s[c]["benign_flows_dropped_pct"]["mean"] for c in cfg_label], 0.4,
                    yerr=[s[c]["benign_flows_dropped_pct"]["sd"] for c in cfg_label], capsize=2, color="tab:blue")
        ax2 = ax.twinx()  # attack-unblocked values are ~100x smaller: own axis
        b2 = ax2.bar(x + 0.2, [s[c]["attack_flows_admitted_pct"]["mean"] for c in cfg_label], 0.4,
                     yerr=[s[c]["attack_flows_admitted_pct"]["sd"] for c in cfg_label], capsize=2, color="tab:orange")
        ax.set_ylabel("benign flows dropped (%)", color="tab:blue")
        ax2.set_ylabel("attack flows not blocked (%)", color="tab:orange")
        ax.set_xticks(x)
        ax.set_xticklabels([c[0] for c in cfg_label])
        ax.set_title("ToN_IoT (real IPs)" if stream == "ton" else "UNSW-NB15 (synthetic sessions)")
        ax.set_xlabel("agent configuration")
        ax2.set_ylim(0, ax2.get_ylim()[1] * 1.35)  # headroom so the legend never covers a bar
        ax.set_ylim(0, ax.get_ylim()[1] * 1.35)
        ax.legend([b1, b2], ["benign dropped (left axis)", "attacks not blocked (right axis)"], fontsize=8, loc="upper right")
    fig.text(0.5, 0.01, "   ".join(v.replace("\\&", "&") for v in cfg_label.values()), ha="center", fontsize=8)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(f"{OUT}/fig4_agent_bars.png", dpi=200)

print(f"parsed {len(results)} RESULT runs, {len(multi)} multiround seeds -> {OUT}/results_tables.tex")
