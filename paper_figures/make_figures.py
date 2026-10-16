"""Builds every paper figure from numbers measured on the AWS EC2 nodes (ap-south-1).
Inputs: results_aws_federated_rows.json (per-seed per-round rows parsed from the node logs) and the
constants below (centralized baseline, 4 unseeded runs; frozen-model evaluation; copied from the node logs)."""
import json, statistics as st
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

rows = json.load(open("results_aws_federated_rows.json")); seeds = list(rows)
# columns: round, cum%, official_fuzzers_recall, replay_acc, general_acc, general_fpr
def col(i): return [[rows[s][r][i] for s in seeds] for r in range(5)]
mean = lambda L: [st.mean(x) for x in L]; sd = lambda L: [st.stdev(x) for x in L]
off, rep, gacc, gfpr = col(2), col(3), col(4), col(5)

CEN = {"unsw_acc": [84.22, 82.87, 82.16, 84.68], "unsw_fpr": [30.14, 34.74, 36.45, 29.18],
       "fuz": [78.47, 86.11, 87.18, 78.39], "ton_acc": [98.93, 98.95, 97.91, 99.01], "ton_fpr": [2.89, 2.27, 5.99, 2.15]}
C_FED, C_CEN, C_GREY = "#1f6feb", "#d1630a", "#6b7280"
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 150})
R = range(5)

# Fig 3: federated (round 4) vs centralized baseline (mean +- sd over 4 unseeded runs)
fig, ax = plt.subplots(figsize=(7, 3.8))
labels = ["UNSW-NB15\naccuracy", "UNSW-NB15\nFPR", "Fuzzers\nrecall", "ToN_IoT\naccuracy"]
fed = [100*st.mean(gacc[4]), 100*st.mean(gfpr[4]), 100*st.mean(off[4]), 98.84]
fed_sd = [100*st.stdev(gacc[4]), 100*st.stdev(gfpr[4]), 100*st.stdev(off[4]), 0]
cen = [st.mean(CEN["unsw_acc"]), st.mean(CEN["unsw_fpr"]), st.mean(CEN["fuz"]), st.mean(CEN["ton_acc"])]
cen_sd = [st.stdev(CEN["unsw_acc"]), st.stdev(CEN["unsw_fpr"]), st.stdev(CEN["fuz"]), st.stdev(CEN["ton_acc"])]
x = range(4); w = 0.38
ax.bar([i-w/2 for i in x], fed, w, yerr=fed_sd, capsize=3, color=C_FED, label="Federated LoRA (round 4, n=4 seeds)")
ax.bar([i+w/2 for i in x], cen, w, yerr=cen_sd, capsize=3, color=C_CEN, label="Centralized baseline (n=4 unseeded runs)")
for i in x:
    ax.text(i-w/2, fed[i]+fed_sd[i]+1, f"{fed[i]:.1f}", ha="center", fontsize=8)
    ax.text(i+w/2, cen[i]+cen_sd[i]+1, f"{cen[i]:.1f}", ha="center", fontsize=8)
ax.set_xticks(list(x)); ax.set_xticklabels(labels); ax.set_ylabel("%"); ax.set_ylim(0, 125)
ax.legend(fontsize=8, loc="upper left", frameon=False); ax.set_title("Federated vs centralized (held-out test sets)")
fig.tight_layout(); fig.savefig("fig3_federated_vs_centralized.png"); plt.close(fig)

# Fig 4: recovery by round
fig, (a1, a2) = plt.subplots(1, 2, figsize=(9, 3.6))
for data, lab, c in ((off, "Official-test Fuzzers recall", C_FED), (rep, "Replay-set Fuzzers accuracy", C_CEN)):
    m = [100*v for v in mean(data)]; s = [100*v for v in sd(data)]
    a1.plot(R, m, marker="o", color=c, label=lab); a1.fill_between(R, [a-b for a, b in zip(m, s)], [a+b for a, b in zip(m, s)], color=c, alpha=0.18)
a1.set_xlabel("Federated round (device 1 reveals 25/50/75/100% of its Fuzzers rows)", fontsize=8); a1.set_ylabel("%"); a1.set_xticks(list(R))
a1.legend(fontsize=8, frameon=False); a1.set_title("Fuzzers recovery (mean ± sd, 4 seeds)", fontsize=10)
m = [100*v for v in mean(gfpr)]; s = [100*v for v in sd(gfpr)]
a2.plot(R, m, marker="s", color=C_GREY, label="General FPR"); a2.fill_between(R, [a-b for a, b in zip(m, s)], [a+b for a, b in zip(m, s)], color=C_GREY, alpha=0.2)
m2 = [100*v for v in mean(gacc)]; a2.plot(R, [100-v for v in m2], marker="^", color="#8b5cf6", label="General error (100 − accuracy)")
a2.set_xlabel("Federated round"); a2.set_ylabel("%"); a2.set_xticks(list(R)); a2.legend(fontsize=8, frameon=False); a2.set_title("Cost on normal traffic", fontsize=10)
fig.tight_layout(); fig.savefig("fig4_recovery_by_round.png"); plt.close(fig)

# Fig 5: tradeoff
fig, ax = plt.subplots(figsize=(5.2, 3.8))
ax.plot([100*v for v in mean(gfpr)], [100*v for v in mean(off)], marker="o", color=C_FED, label="Federated, rounds 0→4")
for r in R: ax.annotate(str(r), (100*mean(gfpr)[r], 100*mean(off)[r]), textcoords="offset points", xytext=(5, -9), fontsize=8)
ax.scatter(CEN["unsw_fpr"], CEN["fuz"], color=C_CEN, label="Centralized baseline runs")
ax.set_xlabel("General false-positive rate (%)"); ax.set_ylabel("Fuzzers recall (%)"); ax.legend(fontsize=8, frameon=False, loc="center right")
ax.set_title("Recall vs false-alarm tradeoff"); fig.tight_layout(); fig.savefig("fig5_recall_fpr_tradeoff.png"); plt.close(fig)

# Fig 7: confusion matrices (frozen model, measured on EC2)
fig, axs = plt.subplots(1, 2, figsize=(7.4, 3.2))
for ax, (title, cm) in zip(axs, (("UNSW-NB15 (82,332)", [[31705, 5295], [5252, 40080]]), ("ToN_IoT (31,656)", [[7355, 145], [222, 23934]]))):
    ax.imshow(cm, cmap="Blues")
    for i in range(2):
        for j in range(2): ax.text(j, i, f"{cm[i][j]:,}", ha="center", va="center", color="white" if cm[i][j] > max(map(max, cm))/2 else "black")
    ax.set_xticks([0, 1]); ax.set_xticklabels(["Normal", "Attack"]); ax.set_yticks([0, 1]); ax.set_yticklabels(["Normal", "Attack"])
    ax.set_xlabel("Predicted"); ax.set_ylabel("Actual"); ax.set_title(title, fontsize=10)
fig.tight_layout(); fig.savefig("fig7_confusion_matrices.png"); plt.close(fig)

def box(ax, xy, wh, text, fc="#eef4ff", ec="#1f6feb", fs=8.5):
    ax.add_patch(FancyBboxPatch(xy, wh[0], wh[1], boxstyle="round,pad=0.02,rounding_size=0.08", fc=fc, ec=ec, lw=1.3))
    ax.text(xy[0]+wh[0]/2, xy[1]+wh[1]/2, text, ha="center", va="center", fontsize=fs)
def arrow(ax, a, b, text="", dy=0.12):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=11, lw=1.2, color="#374151"))
    if text: ax.text((a[0]+b[0])/2, (a[1]+b[1])/2+dy, text, ha="center", fontsize=7.5, color="#374151")

# Fig 1: infrastructure
fig, ax = plt.subplots(figsize=(10, 5.4)); ax.set_xlim(0, 10); ax.set_ylim(0, 5.4); ax.axis("off")
ax.add_patch(FancyBboxPatch((0.1, 0.4), 3.2, 4.6, boxstyle="round,pad=0.02", fc="#f8fafc", ec="#94a3b8", ls="--"))
ax.text(1.7, 4.95, "4 × EC2 t3.small edge nodes (ap-south-1)\nSSM only · no inbound · egress 443", ha="center", fontsize=8, va="top")
for k in range(4): box(ax, (0.3 + (k % 2)*1.5, 3.0 - (k // 2)*1.15), (1.35, 0.95), f"device{k+1}\nEdge agent\nTabular Transformer\n+ LoRA", fs=7.2)
box(ax, (0.3, 0.55), (2.85, 0.6), "systemd service · live capture (scapy)", "#fff7ed", "#d1630a", 7.5)
box(ax, (4.0, 2.2), (1.5, 1.0), "API Gateway\nAPI key / device\n10 req/s plan", "#ecfdf5", "#059669")
lam = [("POST /update\nIngest Lambda", 4.55), ("GET /model\nModel Lambda", 3.75), ("POST /incidents\nIncident Lambda", 2.95), ("GET /rounds, /incidents\nRead Lambdas", 2.15)]
for t, y in lam: box(ax, (6.2, y-0.35), (1.7, 0.7), t, "#fef9c3", "#ca8a04", 7.5)
box(ax, (6.2, 0.9), (1.7, 0.7), "Aggregate Lambda\nEventBridge rate(1 min)\nFedAvg", "#fef9c3", "#ca8a04", 7.2)
box(ax, (8.4, 3.5), (1.4, 0.9), "DynamoDB\nround state\nrounds · incidents", "#fae8ff", "#a21caf", 7.5)
box(ax, (8.4, 1.5), (1.4, 0.9), "S3\nupdates/ · global/\nadapter weights", "#fae8ff", "#a21caf", 7.5)
box(ax, (8.4, 0.4), (1.4, 0.7), "React dashboard\n(incidents + rollout)", "#e0f2fe", "#0284c7", 7.2)
arrow(ax, (3.3, 2.7), (4.0, 2.7), "HTTPS", 0.18)
for t, y in lam: arrow(ax, (5.5, 2.7), (6.2, y))
arrow(ax, (7.9, 4.55), (8.4, 3.95)); arrow(ax, (7.9, 3.75), (8.4, 2.1)); arrow(ax, (7.9, 1.25), (8.4, 1.9)); arrow(ax, (7.9, 1.25), (8.4, 3.6))
arrow(ax, (9.1, 1.5), (9.1, 1.1))
ax.text(5.0, 0.15, "Only LoRA adapter weights (~10.3 KB) and incident metadata leave the node; raw flows never do.", ha="center", fontsize=8.5, style="italic")
fig.savefig("fig1_infrastructure.png", bbox_inches="tight"); plt.close(fig)

# Fig 2: edge-agent loop
fig, ax = plt.subplots(figsize=(10, 3.6)); ax.set_xlim(0, 10); ax.set_ylim(0, 3.6); ax.axis("off")
steps = [("Perceive\nflow record\n(CSV replay or\nlive capture)", 0.2), ("Infer\nTabular Transformer\nclass + confidence", 2.15), ("Decide\nBLOCK  conf ≥ 0.9\nALERT  malicious < 0.9\nRETRAIN  drift / self-eval\nSYNC  every 15 s", 4.1), ("Act\nactuator (iptables or\nsimulated) +\nattention rollout", 6.05), ("Report\nincident → API\nadapter → /update", 8.0)]
for t, x0 in steps: box(ax, (x0, 1.0), (1.75, 1.7), t, fs=7.6)
for x0 in (1.95, 3.9, 5.85, 7.8): arrow(ax, (x0, 1.85), (x0+0.2, 1.85))
box(ax, (4.1, 0.1), (3.7, 0.6), "RETRAIN: 5×20 steps, hard-example sampling, FGSM term → upload LoRA adapter", "#fff7ed", "#d1630a", 7.4)
ax.set_title("Fig. 2  Edge agent decision loop", fontsize=11); fig.savefig("fig2_agent_loop.png", bbox_inches="tight"); plt.close(fig)

summ = {"federated_round4": {"off_fuzzers_recall_pct": [100*st.mean(off[4]), 100*st.stdev(off[4])], "replay_acc_pct": [100*st.mean(rep[4]), 100*st.stdev(rep[4])],
        "general_acc_pct": [100*st.mean(gacc[4]), 100*st.stdev(gacc[4])], "general_fpr_pct": [100*st.mean(gfpr[4]), 100*st.stdev(gfpr[4])]},
        "centralized": {k: [st.mean(v), st.stdev(v)] for k, v in CEN.items()}}
json.dump(summ, open("results_summary.json", "w"), indent=1); print(json.dumps(summ, indent=1))
