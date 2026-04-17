# Major-Project
This is a repository is our major project based on federated learning for intrusion detection system.



# 🛡️ FedShield — Federated Learning-Based Intrusion Detection System

> A distributed, privacy-preserving network intrusion detection system powered by Federated Learning, Agentic AI, and hybrid Transformer + XGBoost models.

---

## 📌 Table of Contents

- [Project Overview](#project-overview)
- [System Architecture](#system-architecture)
- [Tech Stack](#tech-stack)
- [Team & Roles](#team--roles)
- [Repository Structure](#repository-structure)
- [Getting Started](#getting-started)
- [Git Workflow & Branch Guidelines](#git-workflow--branch-guidelines)
- [Commit Convention](#commit-convention)
- [Pull Request & Merge Guidelines](#pull-request--merge-guidelines)
- [Environment Setup](#environment-setup)
- [Contributing](#contributing)
- [Future Enhancements](#-future-enhancements)

---

## Project Overview

**FedShield** is a federated learning-based Intrusion Detection System (IDS) designed for distributed network environments. Traditional IDS solutions require centralized data collection, which raises serious privacy and scalability concerns. FedShield eliminates this by training models **locally at each network node** and sharing only model weights — never raw data — with a central cloud orchestrator.

### Key Innovations

- **Federated Learning Architecture** — Each network node trains its own local model on local traffic data. Only model gradients/weights are sent to the cloud, preserving data privacy across nodes.
- **Agentic AI at Edge Nodes** — Each node hosts an AI agent capable of autonomous decision-making: triggering local retraining, flagging anomalies, and adapting to evolving threat patterns without human intervention.
- **Hybrid ML Models** — A dual-model approach combining **Transformer-based deep learning** (for sequential pattern recognition in network traffic) and **XGBoost** (for fast, interpretable classification of known attack signatures).
- **FedAvg Orchestration** — The cloud server aggregates local model weights from all participating nodes using the **Federated Averaging (FedAvg)** algorithm to produce a continuously improving global model.
- **Privacy by Design** — No raw network traffic ever leaves a node. The system is compliant with data minimization principles.

### Threat Coverage

The system is designed to detect a wide range of network intrusions including but not limited to:
- DoS / DDoS attacks
- Port scanning and reconnaissance
- Man-in-the-Middle (MitM) attacks
- Brute-force and credential stuffing
- Zero-day anomalies (via transformer-based unsupervised signals)

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     CLOUD ORCHESTRATOR                       │
│                                                             │
│   ┌─────────────┐     FedAvg      ┌──────────────────────┐ │
│   │ Global Model│ ◄─────────────► │  Aggregation Engine  │ │
│   └─────────────┘                 └──────────────────────┘ │
│          ▲  ▼  (Model Weights Only — No Raw Data)           │
└──────────┼──┼──────────────────────────────────────────────┘
           │  │
    ┌──────┘  └──────┐
    │                │
┌───▼────────┐  ┌───▼────────┐  ┌────────────┐
│   NODE A   │  │   NODE B   │  │   NODE N   │
│            │  │            │  │            │
│ ┌────────┐ │  │ ┌────────┐ │  │ ┌────────┐ │
│ │AI Agent│ │  │ │AI Agent│ │  │ │AI Agent│ │
│ └────────┘ │  │ └────────┘ │  │ └────────┘ │
│ ┌────────┐ │  │ ┌────────┐ │  │ ┌────────┐ │
│ │XGBoost │ │  │ │XGBoost │ │  │ │XGBoost │ │
│ │+ Trans.│ │  │ │+ Trans.│ │  │ │+ Trans.│ │
│ └────────┘ │  │ └────────┘ │  │ └────────┘ │
│ Local Data │  │ Local Data │  │ Local Data │
└────────────┘  └────────────┘  └────────────┘
  Network Segment A  Network Segment B  ...
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| ML Models | Transformer (PyTorch), XGBoost |
| Federated Learning | Flower (flwr) / PySyft |
| Agentic AI | LangChain / Custom Agent Loop |
| Cloud Orchestrator | Python FastAPI + Docker |
| Model Aggregation | FedAvg (custom implementation) |
| Dataset | CICIDS2017 / NSL-KDD / KDD Cup 99 |
| Communication | gRPC / REST |
| Monitoring | Prometheus + Grafana |
| Version Control | Git + GitHub |

---

## Team & Roles

| Name | Role | Responsibility |
|---|---|---|
| **Mohith Kumar M** | AI/ML Lead | Local model architecture (Transformer + XGBoost), agentic node logic, federated training pipeline, model evaluation |
| **Anusha B** | Cloud Lead | Cloud orchestrator setup, FedAvg aggregation engine, API design, deployment infrastructure, monitoring & logging |

> Both members are expected to maintain clear documentation, write tests for their modules, and follow the Git workflow outlined below.

---

## Repository Structure

```
fedshield/
│
├── cloud/                      # Cloud orchestrator (Anusha)
│   ├── aggregator/             # FedAvg implementation
│   ├── api/                    # FastAPI endpoints
│   ├── monitoring/             # Prometheus/Grafana configs
│   └── Dockerfile
│
├── node/                       # Edge node logic (Mohith)
│   ├── agent/                  # Agentic AI decision loop
│   ├── models/
│   │   ├── transformer/        # Transformer model
│   │   └── xgboost/            # XGBoost classifier
│   ├── training/               # Local federated training
│   └── data_pipeline/          # Traffic data preprocessing
│
├── shared/                     # Shared utilities (both)
│   ├── proto/                  # gRPC protocol definitions
│   ├── utils/                  # Common helpers
│   └── config/                 # Global config files
│
├── datasets/                   # Dataset download scripts
├── tests/                      # Unit + integration tests
├── docs/                       # Architecture diagrams, papers
├── .env.example
├── requirements.txt
├── docker-compose.yml
└── README.md
```

---

## Getting Started

### Prerequisites

- Python 3.10+
- Docker & Docker Compose
- Git
- CUDA-compatible GPU (recommended for transformer training)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/<your-org>/fedshield.git
cd fedshield

# 2. Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy environment config
cp .env.example .env
# Edit .env with your configuration

# 5. Start the cloud orchestrator
docker-compose up --build cloud

# 6. Start a local node (in a separate terminal)
python node/main.py --node-id NODE_A --config config/node.yaml
```

---

## Git Workflow & Branch Guidelines

We follow a **feature branch workflow**. The `main` branch always contains stable, reviewed code. Never push directly to `main`.

### Branch Naming Convention

```
<type>/<short-description>
```

| Type | Usage | Example |
|---|---|---|
| `feature/` | New feature or module | `feature/transformer-model` |
| `fix/` | Bug fix | `fix/fedavg-weight-averaging` |
| `cloud/` | Cloud-specific work | `cloud/aggregator-api` |
| `ml/` | ML/AI model work | `ml/xgboost-classifier` |
| `docs/` | Documentation updates | `docs/architecture-diagram` |
| `test/` | Adding/fixing tests | `test/node-agent-unit` |
| `refactor/` | Code refactoring | `refactor/data-pipeline` |

### Creating a Branch

```bash
# Always branch off from main (pull latest first)
git checkout main
git pull origin main

# Create and switch to your new branch
git checkout -b feature/your-feature-name

# Example
git checkout -b ml/transformer-traffic-classifier
```

### Working on Your Branch

```bash
# Stage your changes
git add .

# Commit with a meaningful message (see Commit Convention below)
git commit -m "feat(ml): add transformer encoder for traffic classification"

# Push your branch to remote
git push origin feature/your-feature-name
```

---

## Commit Convention

We use **Conventional Commits** for clean, readable history.

```
<type>(<scope>): <short description>
```

| Type | Meaning |
|---|---|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation change |
| `refactor` | Code refactor (no feature/fix) |
| `test` | Adding or updating tests |
| `chore` | Build, config, CI/CD changes |
| `perf` | Performance improvement |

**Scope** refers to the module: `ml`, `cloud`, `agent`, `api`, `data`, `shared`

### Examples

```bash
git commit -m "feat(ml): implement XGBoost classifier with SHAP explainability"
git commit -m "feat(cloud): add FedAvg aggregation endpoint"
git commit -m "fix(agent): resolve infinite loop in anomaly detection trigger"
git commit -m "docs: update architecture diagram in README"
git commit -m "test(cloud): add unit tests for model aggregation logic"
```

---

## Pull Request & Merge Guidelines

### Before Opening a PR

- [ ] Your branch is up to date with `main` (`git pull origin main` and rebase if needed)
- [ ] Code runs without errors locally
- [ ] Relevant tests pass
- [ ] You've added comments/docstrings for new functions
- [ ] No hardcoded secrets or API keys in code

### Opening a Pull Request

1. Push your branch to GitHub
2. Go to the repository → **Pull Requests** → **New Pull Request**
3. Set base branch as `main`, compare branch as your feature branch
4. Fill in the PR template:
   - **What does this PR do?**
   - **How to test it?**
   - **Screenshots / logs (if applicable)**
5. Assign the **other team member** as reviewer
6. Add appropriate labels (`ml`, `cloud`, `bug`, `enhancement`)

### Review Process

- The **author** should NOT merge their own PR
- The **reviewer** must approve before merging
- Address all review comments before requesting re-review
- Use **Squash and Merge** to keep commit history clean on `main`

### Resolving Merge Conflicts

```bash
# Update your branch with latest main
git checkout main
git pull origin main
git checkout your-feature-branch
git rebase main

# Resolve conflicts in the flagged files
# Then continue the rebase
git rebase --continue

# Force push (only safe on your own branch)
git push origin your-feature-branch --force-with-lease
```

---

## Environment Setup

Copy `.env.example` to `.env` and fill in:

```env
# Cloud Orchestrator
CLOUD_HOST=localhost
CLOUD_PORT=8000
AGGREGATION_ROUNDS=50
MIN_NODES_PER_ROUND=2

# Node Configuration
NODE_ID=NODE_A
LOCAL_EPOCHS=5
BATCH_SIZE=64
LEARNING_RATE=0.001

# Model
MODEL_TYPE=hybrid          # transformer | xgboost | hybrid
TRANSFORMER_LAYERS=4
TRANSFORMER_HEADS=8

# Dataset
DATASET_PATH=./datasets/CICIDS2017/
```

---

## Contributing

1. Pick up a task from the GitHub Issues / Project board
2. Create a branch following the naming convention
3. Implement, test, and document your changes
4. Open a Pull Request and request review
5. After approval, merge into `main`

For any architectural decisions or major design changes, open a **GitHub Discussion** or raise it in the team channel before implementing.

---

## 🚀 Future Enhancements

The following improvements are planned to further strengthen the system's robustness, accuracy, and real-world applicability.

---

### 1. 🔁 FedProx — Robust Aggregation for Non-IID Data

**Problem:** Vanilla FedAvg breaks down when different network nodes see very different traffic distributions (non-IID data), which is the realistic case in production networks.

**Solution:** Replace FedAvg with **FedProx**, which adds a proximal regularization term to each node's local objective. This stabilizes training across heterogeneous nodes and prevents client drift.

```
L_FedProx = L_local + (μ/2) * ||w - w_global||²
```

> Also explore **per-client personalization layers** on top of the global model for node-specific fine-tuning.

---

### 2. 🤖 True Agentic Behavior at Nodes

**Problem:** Currently the agent wraps the model. A genuinely agentic node should make autonomous decisions beyond just inference.

**Planned agent capabilities:**
- **Concept Drift Detection** — use MMD (Maximum Mean Discrepancy) or KS-test on incoming traffic distributions; auto-trigger local retraining when drift is detected
- **Selective Round Participation** — agent evaluates local model confidence before deciding whether to contribute weights in a given federation round
- **Autonomous Threat Response** — agent can isolate a subnet, throttle suspicious traffic, or generate structured alerts without human intervention

---

### 3. 🔍 Explainable AI (XAI) Integration

**Problem:** A real IDS must justify its alerts to SOC analysts. A black-box model is not deployable in production security environments.

**Planned additions:**
- **SHAP values** for XGBoost — explain which network features (packet size, protocol, port) drove a classification
- **Attention weight visualization** for the Transformer — highlight which time steps in the traffic sequence triggered the alert
- Dashboard overlay showing per-alert feature importance

---

### 4. 🔐 Differential Privacy (DP-SGD)

**Problem:** Even sharing model weights can leak information about local training data through gradient inversion attacks.

**Solution:** Integrate **DP-SGD** using the `Opacus` library during local training. This mathematically bounds the privacy leakage per training round with a formal (ε, δ)-privacy guarantee.

### 5. 🛡️ Byzantine-Robust Aggregation

**Problem:** A compromised node can send poisoned model weights to corrupt the global model — a standard federated learning attack vector.

**Solution:** Add a Byzantine fault detection layer at the cloud orchestrator:
- **Krum aggregation** — selects the update geometrically closest to its neighbors, discarding outliers
- **Coordinate-wise Median** — robust alternative to FedAvg mean aggregation
- **Anomaly scoring on weight updates** — flag nodes whose weight deltas deviate significantly from the round average

---

### 6. 📐 Upgraded Model — TabTransformer / FT-Transformer

**Problem:** A vanilla Transformer is designed for sequential text; network traffic is tabular with mixed feature types.

**Solution:** Replace with **FT-Transformer** (Feature Tokenizer + Transformer), purpose-built for tabular data. Alternatively, prepend a **1D-CNN** as a local feature extractor before the Transformer encoder to capture short-range packet-level patterns.

---

### 7. 📊 Benchmarking & Evaluation Suite

Establish a rigorous evaluation framework to quantify system performance:

| Metric | Target |
|---|---|
| Detection Rate (DR) | > 98% on CICIDS2017 |
| False Positive Rate (FPR) | < 1% |
| F1-Score per attack class | Report per category |
| FL Communication Cost | vs. centralized baseline |
| Accuracy convergence | Across federation rounds |
| Privacy budget (ε) | Track per round with DP |

**Datasets to benchmark on:** CICIDS2017, UNSW-NB15, NSL-KDD

---

### Enhancement Roadmap

| Enhancement | Impact | Effort | Priority |
|---|---|---|---|
| FedProx aggregation | Very High | Low | P0 |
| Concept drift detection in agent | Very High | Medium | P0 |
| SHAP + attention explainability | High | Low | P1 |
| Differential Privacy (Opacus) | High | Medium | P1 |
| Byzantine-robust aggregation | High | Medium | P1 |
| FT-Transformer model upgrade | Medium | Medium | P2 |
| Full benchmark suite on CICIDS2017 | Very High | Medium | P0 |

---

## License

This project is developed for academic and research purposes at **JSS Academy of Technical Education, Bengaluru**.

---

<p align="center">Built with ❤️ by Mohith Kumar M & Anusha B | JSS ATE, Bengaluru</p>
