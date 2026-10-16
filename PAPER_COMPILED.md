# Agentic FedGrid — compiled paper draft (for typing into LaTeX)

Generated 2026-10-16 from `paper_figures/paper_results.tex`, `paper_sections.tex`, `results_tables.tex`,
`figures.tex`, `WRITING_FRAMEWORK.md` and `literature_survey.md`. Every number comes from the EC2 logs.
**Rewrite the prose in your own words. Don't paste it.** Keep the numbers, equations and table contents exactly.

**Status: final.** exp11 (Fuzzers on 2–3 clients / 5× local steps) is done and folded in: the negative federation result is confirmed. New or changed text is marked 🆕.
✍️ = not written yet; you write it from the plan. `[tab:xxx]` / `[fig:xxx]` = `\ref{...}` labels.
`[cite:key]` = a `\cite{key}` you need a bib entry for.

---

## ⚠️ Fix these while you type (found while compiling)

1. **Payload unit mismatch.** The Method says "10.5 KB", but the abstract and ablations say "10.3 KB" / "103.7 KB". The raw value is 10,515 B = 10.3 KiB.
   Pick one unit and use it everywhere: 10.3 KB (r4), 2.8 KB (r1), 5.3 KB (r2), 20.3 KB (r8), 103.7 KB (full).
2. **False table reference.** The Method's cost-aware paragraph says "Table policy_unsw reports sensitivity to them". The table only shows the default costs.
   The sensitivity runs do exist (EC2, 3 seeds, deterministic so sd = 0). Either add the table at the end of this file or delete the sentence.
3. **LLM triage.** Add "and is not evaluated in this paper" to the sentence about the optional Claude-on-Bedrock triage worker. Bedrock access was never enabled.
4. **The abstract is too long.** It runs ~370 words in 2 paragraphs; IEEE conference abstracts are one paragraph of ~150–250 words. Cut it when you retype, keeping the 6-sentence structure in the Writing Guide below.
5. **LaTeX bug, now fixed.** The two agent-table captions in `results_tables.tex` had an extra `}`. It is fixed in `build_results.py` and `results_tables.tex`. If you copied tables earlier, recopy them.
6. **Citations used but undefined:** `fedprox`, `abnar2020`. The full reference list is below.
7. **Ablation-table width.** `tab:ablation` has 8 columns. Use `table*` (two-column span), or it overflows.

---

## Title (pick one)

- **Agentic FedGrid: Cost-Aware Edge Agents with Low-Rank Federated Adaptation for Network Intrusion Detection** (recommended)
- Avoid "novel", "zero-day-proof", "autonomous self-healing", "99% accurate".

**Authors:** Mohith Kumar M, Anusha B, Lokesh Kumar Yadav, Rohan C Ravi; Guide: Dr. Naidila Sadashiv. Dept. of ISE, JSS Academy of Technical Education, Bengaluru.

**Keywords:** Federated learning, intrusion detection, LoRA, tabular Transformer, agentic AI, model poisoning, AWS serverless.

---

## Abstract

Network intrusion detection at the edge must adapt to attacks that only some
sites have seen, without moving raw traffic off the device and without letting
one bad update or one false alarm disrupt legitimate hosts. We present
Agentic FedGrid, a deployed system in which autonomous agents on edge nodes
detect, respond to, and learn from network flows. A frozen tabular Transformer
is adapted with low-rank (LoRA) adapters federated through a serverless AWS
control plane (10.3 KB per upload vs. 103.7 KB for the full model). The
agent chooses actions by expected cost, escalates blocks gradually with
automatic expiry, learns from analyst rollbacks, shares and retracts threat
intelligence with its peers, and adopts a new global model only if it does
not degrade its own held-out performance. All experiments ran on four EC2
nodes with multiple seeds.

Our evaluation is deliberately threshold-free where it matters. Four
federated rounds raise recall on an attack class withheld from pretraining
(Fuzzers) from 41.1% to 54.5% at the default threshold, but the
false-positive rate rises from 14.3% to 19.2%. Moving only the decision
threshold of the frozen backbone to the same FPR yields 53.4%, and the
Fuzzers-vs-benign AUROC does not improve (0.823 vs. 0.818). The apparent
gain is an operating-point shift, a pitfall we expect to affect other
federated IDS evaluations. Spreading the class over three clients or running
5$\times$ more local steps does not change this: recall and FPR rise together
(up to 87.2% at 37.4% FPR), the Fuzzers AUROC stays at 0.817–0.820, and the
frozen model with a moved threshold matches or beats every variant.
Full-model federation degrades the ranking (AUROC 0.962 to 0.950), while LoRA
at the default local budget preserves it (0.959). The robustness
results hold: under a model-replacement attack FedAvg collapses to 47.5%
accuracy, whereas coordinate-wise median aggregation holds 86.5% and the
adoption gate rejects every poisoned model. At the decision layer, the full
agent cuts benign traffic dropped by blocking from 49.8% to 12.5% (ToN_IoT)
and from 22.1% to 2.1% (UNSW-NB15) while letting fewer attacks through. With
an imperfect analyst (10% wrong verdicts) mistaken rollbacks let attacks
through; shortening the learned exception from 30 to 5 minutes cuts that
leakage by about two-thirds. The backbone reaches 87.7% accuracy on the official
UNSW-NB15 test set (gradient-boosted trees: 90.1%), 99.3% on ToN_IoT, and
1.7 ms inference on the edge node.

---

## I. Introduction ✍️ (not written yet, ≈1 page, 5 paragraphs)

- **P1 Context.** IoT/edge networks and rising attack volume. A centralized IDS needs raw traffic shipped to a server, which raises privacy, bandwidth and latency concerns. Cite a general IDS/IoT survey, and only one you have read.
- **P2 Why federated learning, and its gaps.** FL keeps data local, but (a) full-model updates are large, (b) data is non-IID, (c) clients can be poisoned, and (d) most papers stop at classification and never evaluate what the system *does* with a verdict.
- **P3 The response problem.** A per-flow classifier with a block action magnifies false positives per host. That motivates an agent that reasons about action cost, reversibility and feedback.
- **P4 What we do.** One paragraph describing the system. Avoid numbers except maybe 10.3 KB vs 103.7 KB.
- **P5 Contributions + organisation.** Use the list below, then: "Section II reviews related work, Section III describes the system, Section IV the experimental setup, Section V the results; Section VI discusses limitations and Section VII concludes."
- **Don't write:** "first ever", or "novel framework" without hedging. "To the best of our knowledge, no prior work combines …" is allowed only after you check Google Scholar / IEEE Xplore yourself.

### Contributions (end of Introduction)

- A deployed edge–cloud architecture that federates LoRA adapters of a
tabular Transformer IDS through serverless AWS services (API Gateway, Lambda,
DynamoDB, S3), with straggler handling and lock-based round coordination. Raw
flows never leave the device. The live backend closed 12,610 rounds over
25 days.
- An edge agent whose actions go beyond classification: cost-aware action
selection, graded and self-expiring blocks, analyst-feedback rollback with
learned exceptions, peer threat-intel sharing with retraction, and verified
adoption of global models. It is evaluated against both an ideal and an
imperfect analyst.
- A threshold-free evaluation of federated adaptation showing that, in
this setting, the recall gain on an unseen class is fully explained by a
shift of the operating point, including when the class is spread over three
clients or local training is 5$\times$ longer. This is a reporting pitfall for
federated IDS work that uses default-threshold recall.
- A multi-seed evaluation on real cloud hardware: LoRA rank vs.\
full-model federation, FedAvg vs. FedProx vs. median aggregation,
hard-example mining, adversarial training, model poisoning, and the agent's
decision layer. Gradient-boosted and centralized references are included.

---

## II. Related Work ✍️ (not written yet, ≈0.75 page, 4 short subsections)

Cite **only** papers whose PDF you have opened.

- **A. ML/DL IDS on benchmarks:** Pandit et al. (ensembles, CICIDS2017), Bayesh & Hossain (GMM + supervised). Point: centralized, and mostly random splits.
- **B. Federated IDS:** Aouedi et al. FLUIDS (semi-supervised FL); Devi et al. FAT-ViT (federated ViT); plus FetFIDS / Tab-Transformer FL-IDS / FedSecureFormer **if you verify them**. Point: they federate full models and report default-threshold metrics.
- **C. Parameter-efficient FL:** LoRA (Hu et al.), FedITD (PEFT for insider threat), FLASC. Point: LoRA-in-FL exists, but rarely for network-flow IDS.
- **D. Agentic / automated response:** Panwar & Abdelrahman review; Gao/Hammar/Li and IRSDA (if verified). Point: response is studied separately from federated detection.
- **Closing sentence:** the gap is the combination, plus threshold-free evaluation of federated gains.

### Literature table (source material)

## A. Papers in the repo (READ)

| # | Paper | Venue / year | Method | Data | Federated | Edge/LoRA | Drift | Explainable | Relevance |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Devi et al., Vision Transformers-Enhanced Cybersecurity Framework for IDS | ICONSTEM 2025 | FAT-ViT: traffic → 2D image → ViT-Lite, federated adaptive training, contrastive adversarial training. Reports ~98.4% accuracy/F1, 8% better cross-domain generalization, 11% fewer FPs (own claims) | benchmark IDS data | Yes | No LoRA | No | No | **High** — closest competitor |
| 2 | Aouedi et al., FLUIDS | CCNC 2022 | Federated semi-supervised: autoencoder on unlabeled + supervised on labeled | IDS benchmark | Yes | No | No | No | Medium — federated IDS baseline |
| 3 | Panwar & Abdelrahman, Agentic AI in Cybersecurity | ICCA 2025 | Literature review of agentic AI for threat detection/response | — (review) | Mentions as future work | No | Mentions | Mentions black-box problem | Medium — motivation only, no experiments |
| 4 | Lameh et al., Analysis of FL as a Distributed Solution for Learning on Edge Devices | IDSTA 2020 | Empirical FL-on-edge study (accuracy vs number of clients/rounds) | not IDS | Yes | Edge cost | No | No | Low — generic FL/edge background |
| 5 | Bayesh & Hossain, Automated NIDS by Synergizing AI Techniques | RAAICON 2024 | GMM for zero-day anomalies + supervised models for known-attack identification | CICIDS2017 | No | No | No | No | Low–Medium — zero-day vs known split |
| 6 | Pandit et al., IDS with ML + Ensemble learning | InCACCT 2023 | Classical ML ensembles | CICIDS2017 | No | No | No | No | Low — centralized baseline; one sentence at most |

Note: the repo root holds these 6 PDFs plus the synopsis. Only #1 and #3 appear in the synopsis lit review.

## B. Synopsis citations with no PDF in the repo

| Paper (as cited in synopsis) | Claim the project leans on | Status |
|---|---|---|
| Muthuswamy et al. (2026), Hybrid Transformer + XGBoost for Federated IoT IDS | LoRA adapters cut communication overhead by 89.5% | **NOT FOUND** by web search |
| Vijetha (2026), Agentic Intelligence for Unified Cyber Defense (AISAF) | Drift Recovery Index 0.93 via latent-space deviation + confidence | **NOT FOUND** by web search |
| Adam & Baroudi (2024), Federated Learning for IoT: Applications, Trends, Taxonomy | FL survey: non-IID, heterogeneity, communication bottleneck | Not searched; no PDF |

Action: obtain the PDFs and confirm venue/DOI, or remove these from the paper. Do not repeat the 89.5% or 0.93 figures without the source in hand.

## C. Candidate additions (UNVERIFIED — open and confirm before citing)

Federated transformer / tabular IDS
- FetFIDS: Feature Embedding Attention based Federated NIDS (2025) — arXiv 2508.09056
- FedSecureFormer (Dec 2025) — arXiv 2512.24345
- Tab Transformer trust-centric FL-IDS for IoT, Frontiers in Big Data 2025 — doi 10.3389/fdata.2025.1526480
- Efficient Federated Intrusion Detection in 5G using optimized BERT (2024) — arXiv 2409.19390 (quantization, not LoRA)
- Transformers and LLMs for Efficient IDS: A Comprehensive Survey — arXiv 2408.07583

LoRA / communication efficiency
- FedITD, federated PEFT (Adapter/BitFit/LoRA) for insider-threat detection, IEEE Access 2024 — closest LoRA+FL+security paper found
- FLASC: sparse communicated LoRA updates in FL — arXiv 2406.05233 (general FL, not IDS)
- FedShield-LLM — arXiv 2506.05640

Drift
- Incremental Federated Learning for IDS in IoT under Evolving Threat Landscape (Mar 2026) — arXiv 2603.10776
- HDDAF: drift detection and adaptation framework (Lara Gutiérrez et al., 2025)

Agentic response
- Gao, Hammar, Li: In-Context Autonomous Network Incident Response (Feb 2026) — arXiv 2602.13156
- IRSDA: Agent-Orchestrated Framework for Enterprise Intrusion Response (Nov 2025) — arXiv 2511.19644

Explainability
- XNFT: Explainable network flow transformer for DDoS (ECU)
- Search by title: HiT-IDS (attention rollout, not federated), XAI-SecEx, EdgeTrustX

## D. Honest positioning (what the survey can and cannot support)

- Supported by this survey: federated transformer IDS exists (Devi, FetFIDS, FedSecureFormer, Tab Transformer); LoRA-in-FL exists outside IDS (FedITD, FLASC).
- Gap that appears to exist (searches only, not proof): LoRA-adapter federation + on-edge agentic retraining triggers + attention-rollout explanation, together, for network-flow IDS. Verify with Google Scholar / IEEE Xplore / Scopus before writing "first" or "novel".
- Do not claim: mitmproxy interception (not implemented), "zero-knowledge" (no ZK used), sequential/temporal modelling (model attends over one flow's 4 feature tokens). See memory.md §11a.
- Justify the architecture choice over XGBoost by LoRA-compatibility, not by "transformers are better on tabular data".

---

## III. System Model and Methodology

### A. Threat model and setting

*(Place Fig. 1 here: `fig1_infrastructure.png`, label `fig:arch`. The current text never references it, so add \"Fig.~\ref{fig:arch}\" in this paragraph.)*

$K{=}4$ edge nodes (AWS EC2 t3.small, 2 vCPU, 2 GB RAM) each observe network
flows and hold a private, non-IID labelled partition (Dirichlet $\alpha{=}0.5$
over attack categories). Devices 1–2 hold UNSW-NB15 flows and devices 3–4
hold ToN_IoT flows. One UNSW-NB15 category (Fuzzers) is withheld from central pretraining and
from every device except device 1, emulating an attack that only one site has
labelled examples of. Raw flows never leave a device; only adapter weights and
incident metadata cross the network. Coordination runs on AWS serverless
services (API Gateway, Lambda, DynamoDB, S3); nodes authenticate with
per-device API keys. Fig. [fig:arch] shows the architecture.

### B. Flow representation and backbone

Each flow is mapped to a cross-dataset canonical schema of five continuous
features (duration, source/destination bytes, source/destination packets)
and three categorical features (protocol, service, connection state).
Continuous features are transformed as $\tilde x_j = (\log(1+x_j)-\mu_j)/\sigma_j$
with $\mu_j,\sigma_j$ frozen centrally so all devices share one encoding.
Backbone v2 embeds every continuous feature as its own token,
$\mathbf t_j = \tilde x_j \mathbf w_j + \mathbf b_j$ ($\mathbf w_j,\mathbf b_j\in\mathbb R^{d}$),
and every categorical feature through an embedding table, giving
$n{=}8$ tokens of width $d{=}32$. Backbone v1 instead projects all five
continuous features into a single token ($n{=}4$). A two-layer Transformer encoder
(4 heads, FFN width $4d$) is followed by mean pooling and a linear head.
Unless stated otherwise, all federated, ablation and agent experiments use
backbone v1; v2 is evaluated as a backbone and in one federated
replication (Table [tab:fed_rounds_v2]).

### C. Parameter-efficient federated adaptation

After central pretraining the backbone is frozen. Each FFN projection
$W_0\in\mathbb R^{m\times n}$ receives a low-rank update
$$
W = W_0 + \frac{\alpha}{r} B A,\quad A\in\mathbb R^{r\times n},\; B\in\mathbb R^{m\times r},
$$
with $r{=}4$, $\alpha{=}8$, and $B$ initialised to zero. Only $\{A,B\}$ and
the classification head are trained and communicated
($\approx$2.6K parameters, 10.3 KB of float32 per upload).
The server aggregates with FedAvg,
$$
\theta^{t+1} = \sum_{k\in S_t} \frac{n_k}{\sum_{j\in S_t} n_j} \theta_k^{t},
$$
where $S_t$ is the set of devices that reported in round $t$. A round closes
when all $K$ devices report or, via a scheduled straggler handler, after a
timeout with at least one participant. FedProx [cite:fedprox] is evaluated as an
alternative local objective,
$\ell_k(\theta) + \frac{\mu}{2}\lVert\theta-\theta^{t}\rVert^2$, $\mu{=}0.01$.

### D. Local training

Each local update runs a fixed budget of $E{\cdot}S = 5{\times}20$ minibatch
steps (batch 64), independent of buffer size. Minibatches are sampled with
probability proportional to a clipped per-example loss,
$w_i = \min(\ell_i, 3) + 0.3$, recomputed each epoch (online hard-example
mining). Each step minimises clean plus FGSM-perturbed cross-entropy,
$$
\mathcal L = \mathrm{CE}(f(x),y) + \mathrm{CE}\big(f(x+\epsilon \mathrm{sign}(\nabla_x \mathrm{CE}(f(x),y))),y\big),\quad \epsilon{=}0.05,
$$
applied to the normalised continuous features. A shuffled 15% of each
local buffer is held out for the device's own validation.

### E. The edge agent

Each node runs a perceive–decide–act–reflect loop. Unlike a fixed pipeline,
the agent chooses between actions under uncertainty, verifies what it
receives, and adapts from feedback.

**Cost-aware action selection.** For a flow with
$p = P(\text{attack}\mid x)$ the agent takes
$$
a^\ast = \arg\min_{a\in\{NOOP,ALERT,BLOCK\}}
\;(1-p) C(a,\text{benign}) + p C(a,\text{attack}),
$$
with default costs $C(NOOP)=(0,10)$, $C(ALERT)=(1,3)$,
$C(BLOCK)=(20,0)$ (benign, attack). These are deployment
assumptions, not learned values, and must be set per site. The
original rule ($BLOCK$ iff $p\ge0.9$) is kept as a baseline.

**Graded response.** A block on source IP $s$ raises its level
$\lambda_s$. Levels $\lambda_s<4$ are temporary with TTL $60\cdot2^{\lambda_s-1}$ s,
and level 4 is permanent. Expired blocks lift automatically.

**Analyst feedback.** A block an analyst marks as a false positive is
rolled back. The host gets a 30-minute exception (block verdicts downgraded
to alerts), and the benign-side block cost is updated multiplicatively,
$C(BLOCK,\text{benign}) \leftarrow \min(1.1 C, 100)$; a confirmed
block lowers it by 5% (floor 0.1).

**Shared threat intelligence with retraction.** Every 15 s an agent
pulls recent $BLOCK$/$ROLLBACK$ records of its peers from
the cloud incident store. An IP whose latest record is a peer's block is
escalated faster: alerts become blocks, starting one level higher. A
rollback by any device retracts the IP everywhere.

**Verified model adoption.** When a new global model $\theta^{t+1}$
arrives, the agent evaluates it and its current model on its local held-out
set and adopts it only if
$$
\mathrm{Acc}(\theta^{t+1}) \ge \mathrm{Acc}(\theta_k) - 0.01
\;\wedge\;
\mathrm{FPR}(\theta^{t+1}) \le \mathrm{FPR}(\theta_k) + 0.02 .
$$
Otherwise it keeps its model and logs a rejection.

**Autonomous retraining.** A device retrains when the rolling mean
of its top-class confidence over the last 50 flows falls below 0.6
(minimum 20 flows), or when its accuracy on its own labelled buffer falls
below 0.90. Self-evaluation runs at most once per minute, and retraining at
most once per 5 minutes.

**Explanation.** Every BLOCK/ALERT carries an
attention-rollout attribution [cite:abnar2020],
$\hat A^{(l)} = 0.5A^{(l)}+0.5I$ (row-normalised),
$R=\hat A^{(L)}\cdots\hat A^{(1)}$, with token importance given by the column
sums of $R$. This is a heuristic attribution, not a causal explanation.
An optional LLM triage worker (Claude on Amazon Bedrock) summarises
incidents for analysts asynchronously, off the detection path. It receives
only incident metadata and is not evaluated in this paper.

---

## IV. Experimental Setup

All reported numbers were produced on the four EC2 t3.small nodes
(ap-south-1). The federated round experiments execute the deployed Lambda
handler code on the nodes, with DynamoDB and S3 replaced by moto mocks, so that
rounds are reproducible and seeded. The ablation runs execute the same FedAvg
arithmetic in-process. The live backend (API Gateway, Lambda, DynamoDB, S3,
per-device API keys) was exercised separately by the deployed agents: between
21 September and 16 October 2026 it closed 12,610 rounds. Only 22 of them
had all four devices; the scheduled straggler handler closed the rest with one
to three participants. This validates the coordination path under real
partial participation but is not used for any accuracy number. Each
configuration is repeated over 3–4 seeds and reported as mean $\pm$ sample
standard deviation. Test sets are never used for training or model selection:
the official UNSW-NB15 testing set (82,332 flows; 6,062 Fuzzers) and a
stratified 15% ToN_IoT split (31,656 flows). Backbone checkpoints are
selected on a random 15% split of the pretraining pool. Besides
default-threshold metrics we report threshold-free ones: AUROC, Fuzzers-vs-benign
AUROC, and Fuzzers recall at a fixed benign FPR. The threshold for the last is
the corresponding quantile of the model's scores on the benign test flows; it
is an evaluation device and is never used by the deployed system. Reference
models (gradient-boosted trees, scikit-learn `HistGradientBoosting`, and
a centrally trained Transformer) use the same eight features and test sets.

**Agent simulation.** The real agent, actuator and policy code are
driven on a simulated clock, with one flow every 0.05 s distributed
round-robin over four agents. ToN_IoT keeps its real source IPs (47 hosts).
UNSW-NB15's IPs are synthetic, so flows are grouped into synthetic sessions
(300 benign hosts, 5 attacker IPs per category); this grouping is an
assumption. The analyst reviews blocks after 300 s. In the main runs it
reviews every block and is always correct, an upper bound on what feedback can
achieve. A sensitivity study then has it review a random 50% of blocks with a
10% or 20% chance of a wrong verdict, and varies the learned-exception
duration (30 vs. 5 minutes).

---

## V. Results

Write each subsection as: claim → number(s) → table reference → one-line interpretation.

### A. Backbone and reference models

Table [tab:backbone] reports the frozen backbone before any federation.
Moving from one token for all continuous features (v1) to one token per
feature with a longer one-cycle schedule (v2) raises UNSW-NB15 accuracy from
87.19% to 87.73$\pm$0.35%, lowers its FPR from 14.31% to
12.94$\pm$1.13%, and lifts ToN_IoT to 99.28$\pm$0.04% (FPR 1.64%).
Inference stays at 1.7 ms per flow on a t3.small. The better general fit
comes with lower recall on the withheld Fuzzers class before federation
(36.81% vs. 41.06%), so v2 is not uniformly better.

Table [tab:refs] places the backbone between two references trained on
the same eight features. Gradient-boosted trees trained on the same
pretraining pool reach 90.10$\pm$0.17% accuracy at 8.9% FPR, so the
Transformer itself costs about 2.4 points on this split. We keep it because
LoRA federation, FGSM training and attention attribution all require a
differentiable model, and the tree's advantage does not extend to the unseen
class (34.3% Fuzzers recall vs. 41.1%). The backbone scores 97.9% on a
random split of its own pretraining pool. The roughly 10-point drop to the
official test file is distribution shift between the official training and
test files, not a lack of fit. A Transformer trained
centrally on all device data, Fuzzers included, reaches 89.8% Fuzzers recall
but only 82.4% accuracy at 36.4% FPR (3 seeds).

### B. Federated adaptation to an unseen attack class

Fuzzers flows are excluded from pretraining and appear only on device 1,
revealed 25/50/75/100% over four rounds. All metrics are measured on the
global model on device 2, which never sees a Fuzzers flow.

**At the default threshold** (Table [tab:fed_rounds_v1],
Fig. [fig:rounds]), Fuzzers recall rises from 41.06% to
54.50$\pm$1.92% (backbone v1, 4 seeds) and replay-set recall from 28.14% to
43.53%. Accuracy moves only from 87.19% to 86.46%, but the FPR rises from
14.31% to 19.21%. Backbone v2 gives 36.81% $\rightarrow$ 47.39$\pm$9.83%
at 17.01% FPR (Table [tab:fed_rounds_v2]).

**Threshold-free** (Tables [tab:operating], [tab:threshold]), the
picture changes. Across rounds, AUROC stays at 0.962 $\rightarrow$ 0.959, the
Fuzzers-vs-benign AUROC at 0.823 $\rightarrow$ 0.818, and Fuzzers recall at a
fixed 10% FPR falls from 38.0% to 34.8%. Moving only the frozen backbone's
threshold to the FPR each federated variant ends at gives the same recall:
53.4% vs. 54.5% at 19.2% FPR, 51.6% vs. 50.5% at 18.3%, and 57.0% vs.\
59.1% at 21.2%. Federation in this setting therefore moves the operating
point toward "attack"; it does not teach the model to separate Fuzzers from
benign traffic. The information is not absent. The centrally trained model
reaches 0.847 Fuzzers AUROC and 48.1% recall at 10% FPR (one seed).

🆕 **More clients and longer local training.** Two obvious explanations
are that only one of four clients holds the class and that each round runs
only 100 local steps. We tested both on the same Fuzzers flows: split into
disjoint shards over two or three clients, with 5$\times$ more local steps
(500 per round), and both combined (Tables [tab:ablation], [tab:operating], [tab:threshold];
3 seeds each). Default-threshold recall rises to 51.1% (two clients),
71.4% (5$\times$ steps), 79.4% (three clients) and 87.2% (both), but the
FPR rises with it, to 18.5%, 28.2%, 33.6% and 37.4%. The Fuzzers-vs-benign
AUROC stays at 0.817–0.820 in every variant (0.823 before federation), and
recall at 10% FPR stays at 33.8–36.1% (38.0% before). The frozen backbone
with only its threshold moved to the same FPR matches or beats each variant:
51.9% vs. 51.1%, 71.7% vs. 71.4%, 85.1% vs. 79.4%, and 89.7% vs.\
87.2%. Longer local training also costs robustness (FGSM accuracy 74.5%
$\rightarrow$ 53.9%), and with three clients and 5$\times$ steps two of three
seeds collapse (UNSW accuracy 59.8% and 59.6%, AUROC 0.77 and 0.75).
Participation and local budget are therefore not the bottleneck in the regimes
we tested. Together with the full-model result below, which removes the
capacity limit and degrades the ranking further, this suggests that the
binary local objective itself moves the decision boundary rather than the
representation. We regard default-threshold recall as an unreliable measure
of federated gains and report both.

### C. Ablations

Table [tab:ablation] and Fig. [fig:ablation] vary one component at a
time. Unless stated otherwise, each variant uses backbone v1, LoRA $r{=}4$ and
FedAvg, with 3 seeds.

**Rank and full-model federation.** Ranks 1, 2 and 4 behave almost
identically: Fuzzers recall 50.5–52.4%, FPR $\approx$18.3%, at 2.8–10.3 KB
per upload. Rank 8 (20.3 KB) reaches 59.1% at 21.2% FPR. Full-model FedAvg
sends 10$\times$ more data (103.7 KB) and reaches 78.0% recall at 33.1% FPR.
Threshold-free, the full model is worse: AUROC 0.950 vs. 0.959 for LoRA,
30.2% vs. 34.8% Fuzzers recall at 10% FPR, and 78.0% vs. 84.0% for the
frozen backbone at the same 33.1% FPR. Updating every weight from one
site's skewed data degrades the shared ranking. The low-rank restriction
limits this degradation, but it does not produce a gain either.

**Local objective.** FedProx ($\mu{=}0.01$) gives no measurable gain over
FedAvg: 52.4% vs. 50.5% recall and 19.0% vs. 18.3% FPR, both within
one standard deviation. This is consistent with the already bounded local
update, which limits client drift without a proximal term.

**Training components.** Removing FGSM training leaves clean accuracy
essentially unchanged (86.78% vs. 86.47%). Accuracy under an FGSM
perturbation ($\epsilon{=}0.05$) falls from 74.49% to 52.37%. Removing
hard-example mining does not change Fuzzers recall (52.97%), but robustness
becomes unstable across seeds (58.7$\pm$12.8%). We report mining as having
no clear benefit.

**Poisoning.** One client uploads $-10\times$ its honest adapter
(model replacement). Under FedAvg the global model collapses to near-chance
accuracy (47.5$\pm$13.1%), alternating between labelling everything benign
and everything malicious. With the adoption gate, every device rejected every
poisoned global model in all rounds and seeds. However, the isolated devices
keep training only on their own skewed data, and device 2's FPR drifts to
38.8%. Coordinate-wise median aggregation removes the attack at the server:
86.54$\pm$0.21% accuracy and 18.46$\pm$2.20% FPR, matching the clean runs.
Median aggregation on clean data costs little (86.31% accuracy, 20.1% FPR;
AUROC 0.959, identical to FedAvg). The two defences are complementary: the
median protects the shared model, and the gate protects a device if the
server is compromised.

### D. The agentic decision layer

**Action selection** (Tables [tab:policy_unsw], [tab:policy_ton]).
On UNSW-NB15, the cost-aware rule cuts missed attacks from 11.6% to 2.4% of
attack flows and lowers the average cost per flow by 23%. The price is that
it alerts on 31.5% of benign flows instead of 12.6%, which means more
analyst workload. On ToN_IoT both rules are already near-perfect, and the
cost rule halves missed attacks (0.92% $\rightarrow$ 0.39%).

**Response and learning** (Tables [tab:agent_ton], [tab:agent_unsw];
Fig. [fig:agent]). Blocking per source IP magnifies false positives: one
wrong verdict on a busy benign host cuts off all of its later traffic. With
permanent blocks (configuration A) this drops 49.8% of benign ToN_IoT flows
and 22.1% of benign UNSW-NB15 flows.

- Graded, self-expiring blocks (C) reduce this to 28.6% and 1.4%,
without any analyst.
- Analyst rollback with learned exceptions (D) reduces it further, to 9.4% and 1.2%.
- Peer intelligence with retraction (E) costs a little benign traffic
(12.5% and 2.1%) but stops more attacks. Attack flows that get through fall
from 0.029% to 0.019% (ToN_IoT) and from 0.38% to 0.13% (UNSW-NB15)
relative to the threshold-and-block baseline.

With an oracle analyst, the full agent therefore dominates the baseline on
both axes and both datasets.

**Imperfect analyst** (Table [tab:analyst]). In the next experiment,
the analyst reviews only a random half of the blocks and is wrong 10% or
20% of the time. Benign traffic dropped stays well below the baseline
(24.0% vs. 49.8% on ToN_IoT, 4.1% vs. 22.1% on UNSW-NB15 at 10% error).
Attack leakage, however, grows sharply: 4.5% of ToN_IoT attack flows get
through at 10% error and 11.8% at 20% error, against 0.083% for
configuration C with no analyst at all. The cause is the learned exception. A
single wrong rollback of an attacker grants it 30 minutes in which block
verdicts are downgraded to alerts, and the retraction propagates to every
peer. Shortening the exception to 5 minutes cuts the leakage by about
two-thirds (4.5% $\rightarrow$ 1.5% on ToN_IoT and 3.1% $\rightarrow$ 1.1%
on UNSW-NB15 at 10% error). It costs more benign blocking with an ideal
analyst (12.5% $\rightarrow$ 18.6% on ToN_IoT). Analyst feedback is only
worth enabling where analyst verdicts are reliable. Otherwise graded blocks
alone (C) are the safer configuration.

---

## VI. Discussion ✍️ (optional, ≈0.3 page)

- 🆕 Why federation didn't improve separation. It is **not** participation or local budget: with Fuzzers on 2–3 clients or 5× local steps, Fuzzers AUROC stayed at 0.817–0.820 and the moved-threshold frozen model matched or beat every variant. It is not capacity either, since full-model federation is worse. The centralized model *does* separate better (0.847 Fuzzers AUROC, one seed), so the information exists. Hypothesis (untested, say so): the binary local objective moves the decision boundary, not the representation.
- False positives are the real cost in edge IDS, at the model level and amplified at the host level.
- Feedback cuts both ways: it helps only when analyst verdicts are reliable.

---

## VII. Limitations

- On the official UNSW-NB15 split the backbone reaches 87.7% accuracy,
below the $>$96% often reported on random splits (97.9% on our own random
validation split). Gradient-boosted trees on the same eight features reach
90.1%, so about 2.4 points of the gap are attributable to the Transformer
itself; the rest is distribution shift between the official files.
- Federated adaptation did not improve class separation in our setting:
its recall gain equals a threshold shift of the frozen model
(Table [tab:threshold]), and UNSW FPR rises with every round. This held
with one to three of four clients holding the new class and with 100 or 500
local steps per round, over four rounds. More clients, more rounds or other
local objectives may differ.
- FedAvg weights clients by self-reported $n_k$. A malicious client can
inflate its weight. The adoption gate limits but does not remove this.
- Device partitions are drawn from the same pool as pretraining, except
device 1's Fuzzers rows. The (label-free) normalisation statistics were computed
before the ToN_IoT test split was carved out. Recomputing them without the test
rows shifts each feature mean by at most $0.058\sigma$ and each standard deviation
by at most 2.4%; the official UNSW-NB15 test file was never included.
- The headline agent results assume an oracle analyst; with an
imperfect analyst, attack leakage rises sharply (Table [tab:analyst]).
UNSW-NB15 agent results use synthetic host sessions. Live capture was
validated only with loopback scans.
- Four clients only. Round experiments use a mocked cloud backend for
reproducibility; the live backend was validated operationally, not for accuracy.

---

## VIII. Conclusion

Agentic FedGrid shows that low-rank federated adaptation and an agent that
reasons about the cost and trustworthiness of its own actions can be combined
on commodity cloud hardware. The measurements support four conclusions:

- Default-threshold recall overstates federated adaptation. In our
setting, the recall gain on an unseen class is matched by moving the frozen
model's threshold, and the class separation (AUROC) does not improve. This
held with the class spread over up to three clients and with 5$\times$ longer
local training. Federated IDS results should be reported threshold-free.
- Low-rank adaptation does not add discrimination here, but at the default
local budget it preserves the backbone's ranking where full-model federation
degrades it. Median
aggregation together with verified adoption neutralises model-replacement
poisoning.
- The main obstacle in edge intrusion detection is false positives, and
per-host blocking magnifies them. Graded, self-expiring response removes most
of this cost without any human input.
- Human feedback helps only when it is reliable. Mistaken rollbacks are
amplified by learned exceptions and shared retractions, so their duration
must be short.

Future work: federated objectives that change the representation rather than
the threshold, such as contrastive or multi-class local objectives (more
clients holding the class and longer local training did not help here); real
analyst feedback; and temporal (multi-flow)
models that reduce the per-flow false positives behind most of the costs
measured here.

---

## References ✍️ (build your `.bib`; verify every DOI/venue yourself before submitting)

Core methods (well-known; still check the details):
1. H. B. McMahan, E. Moore, D. Ramage, S. Hampson, B. A. y Arcas, "Communication-efficient learning of deep networks from decentralized data," AISTATS 2017. *(FedAvg)*
2. T. Li, A. K. Sahu, M. Zaheer, M. Sanjabi, A. Talwalkar, V. Smith, "Federated optimization in heterogeneous networks," MLSys 2020. *(`fedprox`)*
3. E. J. Hu et al., "LoRA: Low-rank adaptation of large language models," ICLR 2022 (arXiv 2106.09685).
4. S. Abnar, W. Zuidema, "Quantifying attention flow in transformers," ACL 2020. *(`abnar2020`, attention rollout)*
5. A. Vaswani et al., "Attention is all you need," NeurIPS 2017.
6. I. J. Goodfellow, J. Shlens, C. Szegedy, "Explaining and harnessing adversarial examples," ICLR 2015. *(FGSM)*
7. D. Yin, Y. Chen, K. Ramchandran, P. Bartlett, "Byzantine-robust distributed learning: towards optimal statistical rates," ICML 2018. *(coordinate-wise median)*
8. E. Bagdasaryan, A. Veit, Y. Hua, D. Estrin, V. Shmatikov, "How to backdoor federated learning," AISTATS 2020. *(model-replacement attack)*
9. N. Moustafa, J. Slay, "UNSW-NB15: a comprehensive data set for network intrusion detection systems," MilCIS 2015.
10. N. Moustafa, "A new distributed architecture for evaluating AI-based security systems at the edge: Network TON_IoT datasets," Sustainable Cities and Society, 2021.
11. F. Pedregosa et al., "Scikit-learn: Machine learning in Python," JMLR 2011. *(HistGradientBoosting reference model)*

Related work: the 6 PDFs in the repo root (table above), plus any candidate from §C of the literature table **only after you open it**.
**Never cite** Muthuswamy (89.5%) or Vijetha (0.93 DRI) without the PDF in hand.

---

## Figures (put the PNGs next to main.tex)

| Label | File | Placement | Caption |
|---|---|---|---|
| `fig:arch` | `fig1_infrastructure.png` | Section III, `figure` (one column) | Agentic FedGrid architecture: four EC2 edge agents (perceive–decide–act–reflect) exchange only LoRA adapters and incident metadata with a serverless AWS control plane (API Gateway, Lambda, DynamoDB, S3). |
| `fig:rounds` | `fig2_rounds.png` | Results B, `figure` (one column) | Global model per FedAvg round on device 2 (never sees Fuzzers locally): Fuzzers recall at the default threshold (left) and UNSW-NB15 FPR (right), mean ± sd over seeds, EC2. Both rise together; moving the frozen backbone's threshold to the same FPR gives the same recall (Table [tab:threshold]). |
| `fig:ablation` | `fig3_ablation_bars.png` | Results C, `figure*` (0.9\textwidth) | Ablations after four rounds (3 seeds, EC2). Labels give the upload size per device per round. Poisoning results are in Table [tab:ablation]. |
| `fig:agent` | `fig4_agent_bars.png` | Results D, `figure*` (0.9\textwidth) | Agent configurations A (threshold, permanent block) to E (full agent): benign flows dropped and attack flows not blocked, four agents, 3 seeds. |

Preamble: `\documentclass[conference]{IEEEtran}` + `\usepackage{amsmath,booktabs,graphicx,multirow}`. Tables use booktabs (`\toprule \midrule \bottomrule`).

---

## Tables (exact contents, final)

🆕 exp11 added 4 rows to `tab:ablation`, 4 variant blocks to `tab:operating`, and 4 rows to `tab:threshold`. Nothing else changed.

**Table `tab:backbone`.** Frozen backbone before federation: official UNSW-NB15 test set (82,332 flows) and ToN_IoT held-out split (31,656 flows). v1: one token for all continuous features, 10 epochs, single run. v2: one token per feature, 30 epochs, one-cycle LR, mean ± sd over 3 seeds. Trained and evaluated on EC2.

| Metric | v1 | v2 |
|---|---|---|
| UNSW accuracy (%) | 87.19 | 87.73 ± 0.35 |
| UNSW macro-F1 | 0.871 | 0.876 ± 0.004 |
| UNSW FPR (%) | 14.31 | 12.94 ± 1.13 |
| Fuzzers recall (%) | 41.06 | 36.81 ± 0.81 |
| ToN_IoT accuracy (%) | 98.84 | 99.28 ± 0.04 |
| ToN_IoT FPR (%) | 1.93 | 1.64 ± 0.11 |
| Median latency (ms, t3.small) | 1.71 | 1.70 ± 0.02 |

**Table `tab:fed_rounds_v1`.** Global model after each FedAvg round, backbone v1 (mean ± sd over 4 seeds; real Lambda handler code on EC2 t3.small with DynamoDB/S3 mocked).

| Round | Fuzzers recall (%) | Replay acc. (%) | UNSW acc. (%) | UNSW FPR (%) |
|---|---|---|---|---|
| 0 | 41.06 ± 0.00 | 28.14 ± 0.00 | 87.19 ± 0.00 | 14.31 ± 0.00 |
| 1 | 41.36 ± 0.87 | 28.39 ± 1.08 | 87.36 ± 0.25 | 14.05 ± 0.87 |
| 2 | 45.36 ± 0.76 | 32.57 ± 0.92 | 86.82 ± 0.04 | 16.44 ± 0.23 |
| 3 | 48.12 ± 2.13 | 35.90 ± 2.55 | 86.72 ± 0.08 | 17.20 ± 0.73 |
| 4 | 54.50 ± 1.92 | 43.53 ± 1.98 | 86.46 ± 0.07 | 19.21 ± 0.61 |

**Table `tab:fed_rounds_v2`.** Global model after each FedAvg round, backbone v2 (mean ± sd over 3 seeds; real Lambda handler code on EC2 t3.small with DynamoDB/S3 mocked).

| Round | Fuzzers recall (%) | Replay acc. (%) | UNSW acc. (%) | UNSW FPR (%) |
|---|---|---|---|---|
| 0 | 36.81 ± 0.81 | 24.17 ± 1.02 | 87.73 ± 0.35 | 12.94 ± 1.13 |
| 1 | 37.83 ± 1.26 | 25.63 ± 1.24 | 88.02 ± 1.07 | 12.66 ± 2.72 |
| 2 | 41.80 ± 2.08 | 30.15 ± 2.54 | 87.53 ± 0.36 | 15.16 ± 0.48 |
| 3 | 44.22 ± 5.97 | 32.55 ± 7.03 | 87.25 ± 0.03 | 16.46 ± 1.97 |
| 4 | 47.39 ± 9.83 | 36.35 ± 11.74 | 87.30 ± 0.76 | 17.01 ± 4.69 |

**Table `tab:ablation`.** Ablations after 4 federated rounds, global model on device 2 (mean ± sd over 3 seeds; EC2). Payload = raw float32 bytes uploaded per device per round. Adv. acc. = accuracy under FGSM, $\epsilon{=}0.05$, 5,000 test flows.

| Variant | Payload (B) | Fuzzers rec. (%) | UNSW acc. (%) | UNSW FPR (%) | Macro-F1 | Adv. acc. (%) | ToN acc. (%) |
|---|---|---|---|---|---|---|---|
| LoRA $r{=}1$ | 2,835 | 51.25 ± 1.71 | 86.67 ± 0.13 | 18.26 ± 0.69 | 0.864 ± 0.001 | 73.82 ± 1.64 | 98.90 ± 0.04 |
| LoRA $r{=}2$ | 5,403 | 52.42 ± 0.11 | 86.55 ± 0.14 | 18.66 ± 0.30 | 0.863 ± 0.001 | 73.50 ± 1.48 | 98.87 ± 0.01 |
| LoRA $r{=}4$ (default) | 10,515 | 50.48 ± 3.16 | 86.47 ± 0.04 | 18.28 ± 0.83 | 0.862 ± 0.001 | 74.49 ± 0.15 | 98.19 ± 1.09 |
| LoRA $r{=}8$ | 20,763 | 59.12 ± 6.45 | 86.00 ± 0.56 | 21.24 ± 2.66 | 0.857 ± 0.007 | 75.21 ± 1.07 | 97.72 ± 0.97 |
| Full-model FedAvg | 106,155 | 78.04 ± 3.34 | 82.66 ± 0.40 | 33.08 ± 1.80 | 0.817 ± 0.005 | 59.13 ± 13.48 | 95.95 ± 2.51 |
| w/o hard-example mining | 10,515 | 52.97 ± 2.58 | 86.62 ± 0.02 | 18.65 ± 0.70 | 0.864 ± 0.000 | 58.71 ± 12.80 | 98.81 ± 0.05 |
| w/o FGSM training | 10,515 | 50.26 ± 0.15 | 86.78 ± 0.03 | 17.67 ± 0.12 | 0.866 ± 0.000 | 52.37 ± 0.37 | 99.11 ± 0.01 |
| FedProx ($\mu{=}0.01$) | 10,515 | 52.42 ± 3.88 | 86.37 ± 0.10 | 18.98 ± 1.13 | 0.861 ± 0.001 | 74.56 ± 0.16 | 98.81 ± 0.01 |
| Median aggregation | 10,515 | 56.84 ± 3.00 | 86.31 ± 0.15 | 20.14 ± 1.02 | 0.860 ± 0.002 | 75.01 ± 0.89 | 98.21 ± 1.05 |
| + adoption gate | 10,515 | 48.88 ± 4.95 | 86.47 ± 0.12 | 17.83 ± 1.43 | 0.863 ± 0.002 | 74.58 ± 0.34 | 98.18 ± 1.08 |
| Poisoned client, FedAvg | 10,515 | 76.20 ± 41.22 | 47.51 ± 13.08 | 81.25 ± 32.47 | 0.337 ± 0.031 | 44.79 ± 15.57 | 72.06 ± 7.36 |
| Poisoned client, FedAvg + gate | 10,515 | 88.56 ± 3.51 | 81.32 ± 0.69 | 38.82 ± 2.34 | 0.799 ± 0.009 | 76.29 ± 1.14 | 89.56 ± 0.31 |
| Poisoned client, median | 10,515 | 50.86 ± 6.05 | 86.54 ± 0.21 | 18.46 ± 2.20 | 0.863 ± 0.003 | 69.16 ± 13.43 | 98.67 ± 0.03 |
| Fuzzers on 2 clients | 10,515 | 51.15 ± 6.93 | 86.46 ± 0.22 | 18.47 ± 2.19 | 0.862 ± 0.003 | 74.36 ± 0.52 | 98.22 ± 1.02 |
| Fuzzers on 3 clients | 10,515 | 79.42 ± 1.40 | 82.72 ± 0.22 | 33.56 ± 0.83 | 0.818 ± 0.003 | 77.03 ± 0.27 | 98.78 ± 0.02 |
| 5$\times$ local steps | 10,515 | 71.41 ± 11.17 | 84.15 ± 1.92 | 28.24 ± 6.83 | 0.835 ± 0.022 | 53.93 ± 1.34 | 97.10 ± 0.08 |
| 3 clients + 5$\times$ steps | 10,515 | 87.19 ± 4.38 | 67.04 ± 12.69 | 37.36 ± 1.44 | 0.665 ± 0.119 | 54.24 ± 2.40 | 97.63 ± 1.09 |

**Table `tab:policy_ton`.** Per-flow decisions, ToN_IoT (real IPs), default cost table (frozen model).

| Policy | False block (%) | Benign alert (%) | Attack missed (%) | Cost/flow |
|---|---|---|---|---|
| Threshold ($p\geq0.9$) | 1.24 ± 0.00 | 0.69 ± 0.00 | 0.92 ± 0.00 | 0.152 ± 0.000 |
| Cost-aware (Bayes) | 1.28 ± 0.00 | 2.40 ± 0.00 | 0.39 ± 0.00 | 0.126 ± 0.000 |

**Table `tab:agent_ton`.** Four-agent stream simulation, ToN_IoT (real IPs) (3 seeds). Dropped = benign flows refused by an active block; unblocked = attack flows not blocked or dropped.

| Agent configuration | Benign dropped (%) | Attack unblocked (%) | Rollbacks |
|---|---|---|---|
| A: threshold rule, permanent block | 49.79 ± 7.13 | 0.029 ± 0.008 | 0 ± 0 |
| B: cost-aware, permanent block | 51.07 ± 6.75 | 0.028 ± 0.006 | 0 ± 0 |
| C: + graded blocks (TTL) | 28.63 ± 5.67 | 0.083 ± 0.021 | 0 ± 0 |
| D: + analyst rollback & exceptions | 9.40 ± 0.70 | 0.072 ± 0.013 | 34 ± 0 |
| E: + peer intel w/ retraction (full) | 12.50 ± 1.91 | 0.019 ± 0.005 | 42 ± 4 |

**Table `tab:policy_unsw`.** Per-flow decisions, UNSW-NB15 (synthetic sessions), default cost table (frozen model).

| Policy | False block (%) | Benign alert (%) | Attack missed (%) | Cost/flow |
|---|---|---|---|---|
| Threshold ($p\geq0.9$) | 1.69 ± 0.00 | 12.62 ± 0.00 | 11.59 ± 0.00 | 1.012 ± 0.000 |
| Cost-aware (Bayes) | 2.31 ± 0.00 | 31.53 ± 0.00 | 2.36 ± 0.00 | 0.776 ± 0.000 |

**Table `tab:agent_unsw`.** Four-agent stream simulation, UNSW-NB15 (synthetic sessions) (3 seeds). Dropped = benign flows refused by an active block; unblocked = attack flows not blocked or dropped.

| Agent configuration | Benign dropped (%) | Attack unblocked (%) | Rollbacks |
|---|---|---|---|
| A: threshold rule, permanent block | 22.05 ± 0.60 | 0.381 ± 0.044 | 0 ± 0 |
| B: cost-aware, permanent block | 28.35 ± 0.62 | 0.285 ± 0.022 | 0 ± 0 |
| C: + graded blocks (TTL) | 1.42 ± 0.06 | 1.267 ± 0.119 | 0 ± 0 |
| D: + analyst rollback & exceptions | 1.21 ± 0.02 | 1.113 ± 0.160 | 882 ± 8 |
| E: + peer intel w/ retraction (full) | 2.14 ± 0.08 | 0.132 ± 0.032 | 1076 ± 26 |

**Table `tab:operating`.** Threshold-free view of federation (official UNSW-NB15 test set, 3 seeds; EC2). AUROC over all flows, Fuzzers-vs-benign AUROC, and Fuzzers recall at a fixed 10% benign FPR (threshold set on the benign test flows), before (round 0) and after (round 4) federation.

| Variant | Round | AUROC | Fuzzers AUROC | Fuzzers rec. @10% FPR (%) |
|---|---|---|---|---|
| LoRA $r{=}4$ (default) | 0 | 0.962 ± 0.000 | 0.823 ± 0.000 | 37.99 ± 0.00 |
|  | 4 | 0.959 ± 0.001 | 0.818 ± 0.003 | 34.83 ± 1.40 |
| LoRA $r{=}8$ | 0 | 0.962 ± 0.000 | 0.823 ± 0.000 | 37.99 ± 0.00 |
|  | 4 | 0.958 ± 0.001 | 0.818 ± 0.003 | 34.40 ± 1.45 |
| Full-model FedAvg | 0 | 0.962 ± 0.000 | 0.823 ± 0.000 | 37.99 ± 0.00 |
|  | 4 | 0.950 ± 0.003 | 0.809 ± 0.003 | 30.19 ± 0.51 |
| Median aggregation | 0 | 0.962 ± 0.000 | 0.823 ± 0.000 | 37.99 ± 0.00 |
|  | 4 | 0.959 ± 0.001 | 0.817 ± 0.001 | 34.63 ± 0.98 |
| Fuzzers on 2 clients | 0 | 0.962 ± 0.000 | 0.823 ± 0.000 | 37.99 ± 0.00 |
|  | 4 | 0.959 ± 0.001 | 0.818 ± 0.001 | 34.69 ± 0.60 |
| Fuzzers on 3 clients | 0 | 0.962 ± 0.000 | 0.823 ± 0.000 | 37.99 ± 0.00 |
|  | 4 | 0.957 ± 0.000 | 0.818 ± 0.001 | 34.48 ± 0.31 |
| 5$\times$ local steps | 0 | 0.962 ± 0.000 | 0.823 ± 0.000 | 37.99 ± 0.00 |
|  | 4 | 0.956 ± 0.002 | 0.817 ± 0.001 | 33.77 ± 0.86 |
| 3 clients + 5$\times$ steps | 0 | 0.962 ± 0.000 | 0.823 ± 0.000 | 37.99 ± 0.00 |
|  | 4 | 0.826 ± 0.115 | 0.820 ± 0.006 | 36.12 ± 2.98 |

**Table `tab:threshold`.** Federated Fuzzers recall vs. the frozen backbone with only its decision threshold moved to the same benign FPR (official UNSW-NB15 test set; EC2). The frozen model needs no federation at all.

| Federated model | FPR (%) | Fuzzers rec. (%) | Frozen, threshold moved (%) |
|---|---|---|---|
| LoRA $r{=}4$, 4 rounds | 18.28 ± 0.83 | 50.48 ± 3.16 | 51.62 |
| LoRA $r{=}4$, Lambda path (4 seeds) | 19.21 ± 0.61 | 54.50 ± 1.92 | 53.37 |
| LoRA $r{=}8$, 4 rounds | 21.24 ± 2.66 | 59.12 ± 6.45 | 56.96 |
| Full-model FedAvg, 4 rounds | 33.08 ± 1.80 | 78.04 ± 3.34 | 84.00 |
| Fuzzers on 2 clients, 4 rounds | 18.47 ± 2.19 | 51.15 ± 6.93 | 51.93 |
| 5$\times$ local steps, 4 rounds | 28.24 ± 6.83 | 71.41 ± 11.17 | 71.68 |
| Fuzzers on 3 clients, 4 rounds | 33.56 ± 0.83 | 79.42 ± 1.40 | 85.09 |
| 3 clients + 5$\times$ steps, 4 rounds | 37.36 ± 1.44 | 87.19 ± 4.38 | 89.69 |

**Table `tab:analyst`.** Sensitivity of the full agent to the analyst (3 seeds; EC2). The analyst reviews a random 50% of blocks and gives the wrong verdict with the stated probability; a wrong verdict on an attacker rolls its block back and grants it the learned exception.

| Configuration | ToN: Benign dropped (%) | ToN: Attack unblocked (%) | UNSW: Benign dropped (%) | UNSW: Attack unblocked (%) |
|---|---|---|---|---|
| C: no analyst | 28.63 ± 5.67 | 0.083 ± 0.021 | 1.42 ± 0.06 | 1.267 ± 0.119 |
| E: oracle analyst, 30-min exception | 12.50 ± 1.91 | 0.019 ± 0.005 | 2.14 ± 0.08 | 0.132 ± 0.032 |
| E: 50% reviewed, 10% wrong | 23.97 ± 4.54 | 4.543 ± 1.583 | 4.05 ± 0.32 | 3.067 ± 1.217 |
| E: 50% reviewed, 20% wrong | 31.77 ± 8.34 | 11.785 ± 3.186 | 4.13 ± 0.27 | 12.362 ± 1.731 |
| E: oracle, 5-min exception | 18.56 ± 1.58 | 0.018 ± 0.006 | 2.38 ± 0.10 | 0.132 ± 0.032 |
| E: 10% wrong, 5-min exception | 29.16 ± 4.45 | 1.474 ± 0.228 | 4.25 ± 0.14 | 1.063 ± 0.396 |
| E: 20% wrong, 5-min exception | 34.46 ± 6.44 | 4.893 ± 0.235 | 4.40 ± 0.36 | 3.049 ± 0.783 |

**Table `tab:refs`.** Reference models on the same test sets and eight features (3 seeds each; trained and evaluated on EC2). Neither is federated; they bound what the frozen backbone and the federated system are compared against.

| Model (training data) | UNSW acc. (%) | UNSW FPR (%) | Fuzzers rec. (%) | ToN acc. (%) |
|---|---|---|---|---|
| Gradient-boosted trees (pretraining pool, Fuzzers excluded) | 90.10 ± 0.17 | 8.92 ± 0.40 | 34.27 ± 0.25 | 99.55 ± 0.01 |
| Centralized Transformer (all device data incl. Fuzzers) | 82.39 ± 0.45 | 36.38 ± 1.65 | 89.76 ± 1.74 | 98.88 ± 0.07 |
| Backbone v1, frozen (pretraining pool) | 87.19 | 14.31 | 41.06 | 98.84 |
| Backbone v1 + 4 LoRA rounds (federated) | 86.46 ± 0.07 | 19.21 ± 0.61 | 54.50 ± 1.92 | – |

**Optional table `tab:cost_sensitivity`** (needed if you keep the "sensitivity" sentence; fix #2). Per-flow decisions of the frozen model under three cost tables (EC2, 3 seeds, deterministic, sd 0).
Costs are given as (benign, attack). default: NOOP (0,10), ALERT (1,3), BLOCK (20,0). block_cheap: BLOCK (5,0). miss_cheap: NOOP (0,3), ALERT (1,2).

| Dataset | Cost table | Policy | False block (%) | Benign alert (%) | Attack missed (%) | Cost/flow |
|---|---|---|---|---|---|---|
| UNSW | default | Threshold | 1.69 | 12.62 | 11.59 | 1.012 |
| UNSW | default | Cost-aware | 2.31 | 31.53 | 2.36 | 0.776 |
| UNSW | block_cheap | Threshold | 1.69 | 12.62 | 11.59 | 0.898 |
| UNSW | block_cheap | Cost-aware | 10.85 | 22.99 | 2.36 | 0.644 |
| UNSW | miss_cheap | Threshold | 1.69 | 12.62 | 11.59 | 0.510 |
| UNSW | miss_cheap | Cost-aware | 1.63 | 12.68 | 11.59 | 0.507 |
| ToN | default | Threshold | 1.24 | 0.69 | 0.92 | 0.152 |
| ToN | default | Cost-aware | 1.28 | 2.40 | 0.39 | 0.126 |
| ToN | block_cheap | Threshold | 1.24 | 0.69 | 0.92 | 0.108 |
| ToN | block_cheap | Cost-aware | 1.85 | 1.83 | 0.39 | 0.070 |
| ToN | miss_cheap | Threshold | 1.24 | 0.69 | 0.92 | 0.096 |
| ToN | miss_cheap | Cost-aware | 1.24 | 0.69 | 0.92 | 0.096 |

How to read it: when blocking is cheap, the cost rule blocks far more benign flows (UNSW false block 2.3 → 10.9%). When misses are cheap, it collapses to the threshold rule. The cost rule never does worse on cost than the threshold rule, but its behaviour is driven by the cost table, so the costs must be set per deployment.

---

## Writing guide: the 6-sentence abstract

1. **Problem:** edge IDS must adapt to attacks that only some sites see, keep raw traffic local, and not let one bad update or false alarm hurt legitimate hosts.
2. **System:** frozen tabular Transformer + LoRA adapters federated over serverless AWS; edge agent (cost-aware action, graded blocks, rollback, peer intel, gated model adoption).
3. **Setup:** 4 EC2 nodes, UNSW-NB15 official split + ToN_IoT, multiple seeds.
4. 🆕 **Federated result:** default-threshold recall gain is matched by moving the frozen model's threshold; AUROC does not improve, even with the class on 3 clients or 5× local steps. Full-model federation degrades the ranking; LoRA at the default budget preserves it.
5. **What works:** median aggregation + adoption gate against poisoning; the agent cuts benign traffic dropped (49.8→12.5% ToN, 22.1→2.1% UNSW) while letting fewer attacks through; the imperfect-analyst result plus its fix (shorter exception).
6. **Backbone numbers:** 87.7% official UNSW (GBM 90.1%), 99.3% ToN, 1.7 ms.

## NEVER WRITE

- Any accuracy ≥ 90% for **our** model on UNSW-NB15 official test. 97.9% is a random-split validation number; label it as such if you mention it.
- "Federation recovers / learns / detects the unseen Fuzzers class." (Disproved by tab:threshold.)
- "LoRA improves detection." Correct: "At the default local budget LoRA preserves the backbone's ranking; full-model federation degrades it." (With 3 clients + 5× steps, LoRA collapsed in 2 of 3 seeds.)
- "More clients / longer local training makes federation learn Fuzzers." exp11 says no: recall up only with FPR, AUROC flat.
- "Federation reaches 87% Fuzzers recall." Only at 37.4% FPR, and the frozen model gets 89.7% there.
- "Zero-day detection", "zero-knowledge", "mitmproxy", "temporal/sequence modelling", "real-time blocking in production" (blocking ran in simulate mode; REAL_BLOCK never on).
- "Real analyst" / "deployed with SOC". The analyst is simulated.
- Any LLM-triage result.
- "Scales to N devices." Only 4 were tested.
- "Live federated training produced X% accuracy." Live backend = operational validation only.
- Numbers from Muthuswamy (89.5%) or Vijetha (0.93) without PDFs.
- "Hard-example mining improves …" or "FedProx improves …" (both no gain).

## FACT SHEET (the only numbers you may use)

Format: value — source table. "±" = sample sd over seeds.

**Data / setup**
- UNSW official test: 82,332 flows, 6,062 Fuzzers. ToN test: 31,656 flows, 47 source IPs. 4 × EC2 t3.small (2 vCPU, 2 GB), ap-south-1.
- Dirichlet α = 0.5; devices 1–2 UNSW, 3–4 ToN; Fuzzers only on device 1, revealed 25/50/75/100%.
- LoRA r=4, α=8, ≈2.6K trainable params; upload 10,515 B (r4), 2,835 (r1), 5,403 (r2), 20,763 (r8), 106,155 (full) — tab:ablation.
- Local: 5×20 steps, batch 64, FGSM ε=0.05, mining wᵢ=min(ℓᵢ,3)+0.3, 15% local val. FedProx μ=0.01.
- Agent: costs NOOP(0,10) ALERT(1,3) BLOCK(20,0); TTL 60·2^(λ−1) s, permanent at level 4; exception 30 min; intel pull 15 s; gate tol acc 0.01 / FPR 0.02; retrain if confidence < 0.6 over 50 flows or local acc < 0.90; cooldown 5 min.

**Backbone** — tab:backbone
- v1: UNSW acc 87.19, F1 0.871, FPR 14.31, Fuzzers 41.06; ToN 98.84 / FPR 1.93; 1.71 ms.
- v2 (3 seeds): UNSW 87.73±0.35, F1 0.876±0.004, FPR 12.94±1.13, Fuzzers 36.81±0.81; ToN 99.28±0.04 / FPR 1.64±0.11; 1.70 ms.
- Random-split validation: 97.9 (pretraining pool, not the official test).

**References** — tab:refs (3 seeds each)
- GBM: acc 90.10±0.17, FPR 8.92±0.40, Fuzzers 34.27±0.25, ToN 99.55±0.01.
- Centralized Transformer: acc 82.39±0.45, FPR 36.38±1.65, Fuzzers 89.76±1.74, ToN 98.88±0.07. One seed: Fuzzers AUROC 0.847, Fuzzers recall @10% FPR 48.1.

**Federation, default threshold** — tab:fed_rounds_v1 / v2
- v1 (4 seeds) round 0→4: Fuzzers 41.06→54.50±1.92; replay 28.14→43.53; acc 87.19→86.46±0.07; FPR 14.31→19.21±0.61.
- v2 (3 seeds): Fuzzers 36.81→47.39±9.83; acc 87.30; FPR 12.94→17.01±4.69.

**Federation, threshold-free** — tab:operating, tab:threshold
- AUROC 0.962→0.959 (r4); Fuzzers AUROC 0.823→0.818; Fuzzers recall @10% FPR 37.99→34.83±1.40.
- Full model: AUROC 0.950, Fuzzers AUROC 0.809, @10% FPR 30.19.

**Federation, more clients / longer local training (exp11, 3 seeds, round 4)** — tab:ablation, tab:operating, tab:threshold
- Same Fuzzers rows split into disjoint shards over k clients; long = 100 steps/epoch × 5 = 500 local steps/round. lora_r4 rerun reproduced exp10 exactly.
- Fuzzers rec / FPR / UNSW acc / Fuzzers AUROC / rec@10% FPR / FGSM acc:
  - 2 clients: 51.15±6.93 / 18.47±2.19 / 86.46 / 0.818 / 34.69 / 74.36
  - 3 clients: 79.42±1.40 / 33.56±0.83 / 82.72 / 0.818 / 34.48 / 77.03
  - 5× steps: 71.41±11.17 / 28.24±6.83 / 84.15±1.92 / 0.817 / 33.77 / 53.93
  - 3 clients + 5× steps: 87.19±4.38 / 37.36±1.44 / 67.04±12.69 / 0.820 / 36.12 / 54.24; AUROC 0.826±0.115 (seeds 456/789 collapse: acc 59.8/59.6, AUROC 0.774/0.745).
- Frozen backbone, threshold moved to same FPR: 51.93 @18.5%, 71.68 @28.2%, 85.09 @33.6%, 89.69 @37.4%.
- Frozen backbone with threshold moved: 51.62 @18.3% FPR (vs fed 50.48), 53.37 @19.2% (vs 54.50), 56.96 @21.2% (vs r8 59.12), 84.00 @33.1% (vs full 78.04).

**Ablations** (3 seeds, round 4) — tab:ablation
- r1 Fuzzers 51.25 / acc 86.67 / FPR 18.26 / FGSM-acc 73.82; r2 52.42/86.55/18.66/73.50; r4 50.48/86.47/18.28/74.49; r8 59.12/86.00/21.24/75.21; full 78.04/82.66/33.08/59.13.
- no_mining 52.97/86.62/18.65, FGSM 58.71±12.8; no_adv 50.26/86.78/17.67, FGSM 52.37; FedProx 52.42/86.37/18.98/74.56; median 56.84/86.31/20.14/75.01; gated 48.88/86.47/17.83.
- Poison FedAvg acc 47.51±13.08 (FPR 81.25); poison+gate acc 81.32, FPR 38.82, 100% of poisoned globals rejected; poison+median acc 86.54±0.21, FPR 18.46±2.20.

**Decision policy** (default costs) — tab:policy_*
- UNSW threshold: miss 11.59, benign alert 12.62, false block 1.69, cost 1.012 → cost rule: miss 2.36, alert 31.53, false block 2.31, cost 0.776 (−23%).
- ToN miss 0.92 → 0.39.

**Agent simulation** (3 seeds; benign dropped % / attack unblocked %) — tab:agent_*
- ToN: A 49.79/0.029, B 51.07/0.028, C 28.63/0.083, D 9.40/0.072, E 12.50/0.019.
- UNSW: A 22.05/0.381, B 28.35/0.285, C 1.42/1.267, D 1.21/1.113, E 2.14/0.132.

**Imperfect analyst** — tab:analyst (ToN dropped/unblocked | UNSW dropped/unblocked)
- E, 10% wrong: 23.97 / 4.543 | 4.05 / 3.067.  E, 20% wrong: 31.77 / 11.785 | 4.13 / 12.362.
- E oracle, 5-min exception: 18.56 / 0.018 | 2.38 / 0.132.
- E, 10% wrong, 5-min: 29.16 / 1.474 | 4.25 / 1.063.  E, 20% wrong, 5-min: 34.46 / 4.893 | 4.40 / 3.049.

**Live deployment** (operational only)
- 12,610 rounds closed, 21 Sep – 16 Oct 2026; 22 with all 4 devices, rest via straggler handler. 6 Lambdas, API Gateway with per-device API keys.

**Data hygiene**
- Normalisation stats include ToN test rows: ≤0.058σ mean shift, ≤2.4% std change. UNSW official test never included.
