# Literature survey working file — Agentic FedGrid

Status key: **READ** = abstract/key sections read from the PDF in repo root. **UNVERIFIED** = found only via search snippet; open the paper and confirm before citing. **NOT FOUND** = cited in the synopsis, no PDF in the repo and not found by web search.

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
