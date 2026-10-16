# Agentic FedGrid — paper writing framework

How to use this: write each section in your own words, paragraph by paragraph,
following the prompts. **Only use numbers from the Fact Sheet (§ at the end).**
Every number there was produced on the EC2 nodes and is in
`paper_figures/aws_logs/` → `results_final.json` → `results_tables.tex`.
If a number you want is not in the Fact Sheet, you don't have it — don't write it.

Target: IEEE conference format, ~6–8 pages. Ready-made text you may reuse or
rewrite: `paper_results.tex` (Abstract, Contributions, Results, Conclusion),
`paper_sections.tex` (Method, Setup, Limitations). Tables: `\input{results_tables.tex}`.
Figures: `figures.tex`.

---

## 0. Title
Say what it is; don't oversell.
- OK: "Agentic FedGrid: Cost-Aware Edge Agents with Low-Rank Federated Adaptation for Network Intrusion Detection"
- Avoid: "novel", "zero-day-proof", "autonomous self-healing", "99% accurate".

## 1. Abstract (≈200–250 words). Use these 6 sentences:
1. **Problem:** edge IDS must adapt to attacks that only some sites see, keep raw traffic local, and not let one bad update or false alarm hurt legitimate hosts.
2. **System:** frozen tabular Transformer + LoRA adapters federated over serverless AWS; edge agent (cost-aware action, graded blocks, rollback, peer intel, gated model adoption).
3. **Setup:** 4 EC2 nodes, UNSW-NB15 official split + ToN_IoT, multiple seeds.
4. **Honest federated result:** default-threshold recall gain is matched by moving the frozen model's threshold; AUROC does not improve. Same with Fuzzers on 2–3 clients or 5× local steps (exp11). Full-model federation degrades the ranking; LoRA at the default local budget preserves it.
5. **What works:** median aggregation + adoption gate against poisoning; the agent cuts benign traffic dropped (49.8→12.5% ToN, 22.1→2.1% UNSW) while letting fewer attacks through; imperfect analyst result plus the fix (shorter exception).
6. **Backbone numbers:** 87.7% official UNSW (GBM 90.1%), 99.3% ToN, 1.7 ms.

## 2. Introduction (≈1 page, 5 paragraphs)
- **P1 Context.** IoT/edge networks, rising attack volume; centralized IDS needs raw traffic shipped to a server, which raises privacy, bandwidth and latency concerns. (Cite a general IDS/IoT survey. Use only papers you have read.)
- **P2 Why federated learning, and its gaps.** FL keeps data local, but (a) full-model updates are large, (b) non-IID data, (c) poisoned clients, (d) most papers stop at classification, so nobody evaluates what the system *does* with a verdict.
- **P3 The response problem.** A per-flow classifier with a block action magnifies false positives per host. Motivates an agent that reasons about action cost, reversibility and feedback.
- **P4 What we do.** One paragraph describing the system (don't repeat numbers here except maybe 10.3 KB vs 103.7 KB).
- **P5 Contributions.** Paste/adapt the 4-item list from `paper_results.tex`. End with the paper organisation ("Section II reviews…").

**Do not write:** "first ever", "novel framework" without hedging. Allowed: "to the best of our knowledge, no prior work combines …", and only after you check Google Scholar/IEEE Xplore yourself.

## 3. Related Work (≈0.75 page, 4 short subsections)
Source: `literature_survey.md`. Cite **only** papers whose PDF you have opened.
- **A. ML/DL IDS on benchmarks:** Pandit et al. (ensembles, CICIDS2017), Bayesh & Hossain (GMM + supervised). Point: centralized, and mostly random splits.
- **B. Federated IDS:** Aouedi et al. FLUIDS (semi-supervised FL); Devi et al. FAT-ViT (federated ViT); plus FetFIDS / Tab-Transformer FL-IDS / FedSecureFormer **if you verify them**. Point: they federate full models and report default-threshold metrics.
- **C. Parameter-efficient FL:** LoRA (Hu et al. 2021), FedITD (PEFT for insider threat), FLASC. Point: LoRA-in-FL exists, but rarely for network-flow IDS.
- **D. Agentic / automated response:** Panwar & Abdelrahman review; Gao/Hammar/Li, IRSDA (if verified). Point: response is studied separately from federated detection.
- **Closing sentence:** the gap is the combination, plus threshold-free evaluation of federated gains.

**Remove unless you have the PDF:** Muthuswamy et al. (89.5% claim), Vijetha (0.93 DRI), the two IEEE links. Never repeat their numbers without the source in hand.

## 4. System Model & Methodology. Already written in `paper_sections.tex`
Order: threat model/setting → features & backbone (v1 vs v2!) → LoRA + FedAvg/FedProx/median → local training (mining, FGSM) → edge agent (cost policy, graded response, feedback, intel sharing, gated adoption, retraining triggers, explanation).
- Put Fig. 1 (architecture) here.
- Keep every equation as written; the code implements exactly these.
- **Must keep:** "all federated, ablation and agent experiments use backbone v1."
- Explanation = attention rollout, a *heuristic*, not causal. LLM triage: describe it as **optional and not evaluated** (Bedrock access was never enabled). Do not report any triage results.

## 5. Experimental Setup. Already written in `paper_sections.tex`
Cover: hardware (4× t3.small), datasets & splits (official UNSW test 82,332 flows / 6,062 Fuzzers; ToN 15% split 31,656), Fuzzers withheld protocol, seeds (3–4), metrics (default-threshold **and** threshold-free), mocked vs live backend, agent simulation assumptions (DT 0.05 s, 47 real ToN IPs, synthetic UNSW sessions, analyst models), references (GBM, centralized).

## 6. Results. Order and what each subsection must say
| Subsection | Tables/Figs | The one-sentence takeaway |
|---|---|---|
| A. Backbone & references | tab:backbone, tab:refs | 87.7% official split; GBM 90.1% (≈2.4 pts is the model, the rest is split shift); v2 not uniformly better |
| B. Federated adaptation | tab:fed_rounds_v1, fig:rounds, tab:operating, tab:threshold | default-threshold recall ↑ but AUROC flat; frozen threshold shift matches it → operating-point shift, not learning |
| C. Ablations | tab:ablation, fig:ablation | ranks 1–4 ≈ same; full model ranks worse; FedProx & mining no gain; FGSM matters |
| D. Poisoning | tab:ablation (poison rows) | FedAvg collapses; median holds; gate rejects all but isolates devices |
| E. Decision policy | tab:policy_unsw, tab:policy_ton | cost rule: fewer misses, more alerts |
| F. Agent response | tab:agent_ton, tab:agent_unsw, fig:agent | graded blocks do most of the work; full agent beats baseline on both axes (oracle analyst) |
| G. Imperfect analyst | tab:analyst | wrong rollbacks leak attacks; 5-min exception cuts that by ≈2/3; C is safest without a reliable analyst |

Write each as: claim → number(s) → table reference → one-line interpretation. Don't add interpretations beyond what's in `paper_results.tex`.

## 7. Discussion (optional, ≈0.3 page)
- Why federation didn't improve separation: NOT participation or local budget. exp11 spread Fuzzers over 2–3 clients and ran 5× local steps; Fuzzers AUROC stayed 0.817–0.820 and the moved-threshold frozen model matched or beat every variant. Not capacity either (full model is worse). The centralized model *does* separate better (0.847 Fuzzers AUROC, one seed), so the information exists. Remaining candidate (hypothesis, untested): the binary local objective moves the boundary, not the representation.
- False positives are the real cost in edge IDS, at the model level and amplified at the host level.
- Feedback is a double-edged sword.

## 8. Limitations. Already written; keep every bullet
Official-split ceiling, no federated discrimination gain, self-reported n_k, partition overlap + normalisation note, oracle/synthetic agent assumptions, 4 clients + mocked backend for accuracy.

## 9. Conclusion. Already written (4 bullets + future work)

---

## NEVER WRITE (each of these is false or unsupported)
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

---

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
