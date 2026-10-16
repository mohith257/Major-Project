# Agentic FedGrid — Project Memory

Living design doc. This is the source of truth for architecture decisions,
superseding the original synopsis wherever the two disagree (the synopsis
was the pitch; this is the as-built design). Update this file whenever a
real decision is made — don't let it drift out of sync with the code.

**READ §12 FIRST if citing any number from §4/§7/§11*.** A real bug (LoRA
base weights frozen at random init, never trained, from the very first
commit through 2026-09-14) meant every accuracy/Fuzzers-recovery/FPR
number in this file before that date was measured against a backbone
whose FFN sublayers were permanently random. Fixed 2026-09-14, backbone
retrained, everything re-measured. Numbers in §4/§7/§11* are kept for
historical record (they document real debugging work) but are
SUPERSEDED — cite §12's numbers in the paper/report, not the earlier
ones.

## 1. Identity

- **Project**: Agentic FedGrid — Autonomous Privacy-Preserving Intrusion
  Detection via Federated Learning and Agentic AI.
- **Course**: BIS786, Final Year Project, Dept. of ISE, JSS Academy of
  Technical Education, Bengaluru. Batch 2025-26.
- **Team**: Mohith Kumar M (1JS23IS090), Anusha B (1JS23IS016),
  Lokesh Kumar Yadav (1JS22IS065), Rohan C Ravi (1JS24IS410).
- **Guide**: Dr. Naidila Sadashiv.

## 2. What "agentic" means here (say this explicitly in the report)

The classifier (Tabular Transformer), the FedAvg aggregator, and the
firewall actuator are all *tools*. None of them decide anything by
themselves. `edge_agent/agent.py`'s `EdgeAgent` class is the controller
that owns a **perceive → decide → act → reflect** loop and autonomously
picks which tool to invoke, with no fixed schedule and no cloud command
telling it what to do next. Two devices on the identical global model can
make different decisions at the same instant because their local context
(recent traffic, their own labeled buffer, their own blocklist state)
differs — that's the property that separates this from a cron job, and the
thing to defend against a jury question of "isn't this just automation?"

## 3. System architecture (layers)

1. **Edge Device Layer** (4 nodes, see §5) — traffic replay/perception,
   local inference, drift/self-eval monitoring, local retraining, defense
   actuation, upload/download comms.
2. **Communication Layer** — HTTPS to API Gateway. Only LoRA adapter
   weights + metadata (device id, sample count) cross this boundary. Never
   raw flow data. Per-device API key (API Gateway usage plan).
3. **Cloud Orchestration Layer** (AWS serverless) — see §6.
4. **Model Layer** — frozen shared backbone + per-device LoRA adapter, see
   §7.
5. **Defense Layer** — local blocklist/iptables actuator + shared
   `threat_intel` table for cross-device IP broadcast (independent of
   FedAvg — a second, faster privacy-preserving collaboration channel).
6. **Dashboard** — React, polls the API for round metrics + incident feed
   + attention-rollout for a selected detection.

## 4. Dataset & partition plan

- **Two datasets required** (locked decision): UNSW-NB15 + ToN_IoT (or
  BoT-IoT as a fallback) — chosen because both come from the same UNSW
  Canberra Cyber research group using the same Argus-based flow-feature
  pipeline, so their schemas overlap heavily. Do **not** pair with
  NSL-KDD — different era, different feature-extraction pipeline, would
  require building a translator from scratch.
- **Canonical schema** = intersection of semantically equivalent fields
  (proto, duration, src/dst bytes, src/dst pkts, src/dst ttl, service,
  state, label, attack_cat). Drop dataset-specific extras rather than
  imputing — simpler to defend than a made-up imputation strategy.
- Categorical vocab (proto/service/state) must be built from the union of
  both datasets' values and frozen/shipped identically to all 4 devices —
  if devices built their own encodings independently, adapters wouldn't be
  averageable (index collisions).
- **Core detection target: binary** (normal/attack) — both datasets agree
  on this natively. Multi-class attack-category taxonomy reconciliation is
  a stretch goal, not required for the core FedAvg deliverable.
- **Non-IID split**: Dirichlet(α) label-skew partition across devices
  (Hsu et al. 2019) — not random/IID, that would make the FL story too
  easy to prove.
- **Device assignment**: 2 devices on UNSW-NB15 shards, 2 devices on
  ToN_IoT shards (frames as "enterprise-network edge sites" vs
  "IoT-network edge sites" — ties back to the synopsis's own IoT-growth
  framing).

### Hold-out "zero-day" design (for the core demo)

- One attack category (`HOLD_OUT_ATTACK_CATEGORY`, currently placeholder
  `"Backdoor"` — confirm it exists with enough samples once real data is
  in hand) is:
  - **Excluded entirely** from central backbone pretraining.
  - **Present only in Device 1's** local labeled training partition —
    assigned deliberately, not left to random Dirichlet draw.
  - **Zero samples** in Devices 2–4's partitions.
- A held-out **replay set** is carved from the same category — samples
  Device 1 never trained on either — used only for live injection during
  the demo, so detection proves generalization, not memorization.
- See §8 for the demo script that uses this.

**Verified against real data 2026-08-23** — `data/scripts/partition_data.py`
is finalized and has been run successfully end to end. Key findings that
changed the plan from earlier assumptions:

- **UNSW-NB15 pre-split train/test CSV has no `sttl`/`dttl` and no IP
  columns at all** (the official benchmark set strips IPs deliberately, to
  stop a classifier memorizing attacker IPs instead of learning traffic
  patterns). Canonical continuous schema is therefore just `duration,
  src_bytes, dst_bytes, src_pkts, dst_pkts` — not TTL/load as originally
  guessed. IP is **not a model feature** anywhere in this system; it's
  demo-only metadata for the block actuator. For UNSW-sourced devices
  (1, 2), IPs are synthesized (`synthesize_ip()`) purely for the demo
  display since none exist in the source data; ToN_IoT-sourced devices
  (3, 4) use real `src_ip`/`dst_ip` from the dataset.
- **UNSW's `proto`** enumerates the full IANA protocol name list (~130
  values, Argus behaviour); **ToN_IoT's `proto`** is just `{tcp, udp,
  icmp}` (Zeek). Bucketed both to a shared `{tcp, udp, icmp, other}` via
  `bucket_proto()`.
- **UNSW's `state`** (Argus) and **ToN_IoT's `conn_state`** (Zeek) are
  different state machines with zero overlapping string values — verified
  directly, not assumed. Bucketed both to `{established, rejected_reset,
  incomplete_other}` via `bucket_state()`/`STATE_BUCKET_MAP` rather than
  dropping the signal or falsely merging incompatible vocabularies.
- **`service`**: UNSW and ToN_IoT vocabularies overlap substantially
  (`dns`, `http`, `ssl`, `ftp`, `-` common to both) with some values unique
  to each side (UNSW: irc/pop3/radius/snmp/smtp; ToN_IoT: dce_rpc/gssapi/
  smb/smb;gssapi). Used as the **union** of both, 17 values + UNK.
- **Frozen vocab must be built from the full value space before any
  row-exclusion filtering** — first run of the script silently dropped
  `smb`/`smb;gssapi` from the service vocab because those values only
  occur in ToN_IoT rows tagged `type=='backdoor'`, which get excluded from
  training. Since the hold-out replay set (drawn from UNSW's `Backdoor`
  class) could plausibly need those tokens too, building vocab after
  filtering would have caused an unrecognized-category failure at demo
  time. Fixed: vocab is built first, filtering happens after. Also added
  an explicit `__unk__` token to every categorical vocab as a general
  fallback — any live-deployed IDS eventually sees a value it never
  trained on.
- **`label` convention confirmed** (crosstab against `attack_cat`/`type`):
  `0` = normal, `1` = attack, consistent in both datasets.
- **Hold-out class collision caught**: ToN_IoT has its *own* `backdoor`
  type (n=20,000, unrelated to UNSW's `Backdoor` attack_cat, n=1,746).
  Left unhandled, devices 3/4 (ToN_IoT-sourced) would have trained on
  backdoor traffic and silently invalidated the entire "only device 1 has
  seen this attack" demo premise. Fixed: ToN_IoT rows with
  `type=='backdoor'` are dropped from the ToN_IoT pool entirely (used by
  no device) — see `HOLD_OUT_ATTACK_CATEGORY_TONIO` in the script.
- **Hold-out class changed from "Backdoor" to "Fuzzers" after empirical
  testing 2026-08-23** (`model/validate_holdout.py` + a throwaway
  candidate comparison script). Backdoor was rejected: the frozen backbone
  already detected 97.5% of it zero-shot, leaving no before/after to show
  — binary attack/normal classifiers generalize across attack categories
  more than expected, so excluding one category from training doesn't
  reliably blind the model to it. Tested 4 candidates (source, category,
  n, zero-shot-before, after-1-local-retrain):
  `tonio/injection (20000): 0.991→0.997`, `tonio/xss (20000): 0.894→0.985`,
  `unsw/Analysis (2000): 1.000→1.000`, **`unsw/Fuzzers (18184): 0.348→0.522`**
  (5-epoch throwaway backbone). Only Fuzzers showed a real gap — consistent
  with the lit review (Muthuswamy et al.) flagging exactly this style of
  attack (payloads that closely resemble legitimate traffic) as hard to
  detect. Re-validated with the actual 10-epoch production backbone using an
  artificially clean, isolated Fuzzers-only training slice (no benign
  examples mixed in): 0.213 → 0.365 (+0.152). **This number is now
  superseded — see §11b for the full story**: testing against Device 1's
  actual realistic full local buffer first dropped this to +5.7pt
  (dilution), then a buggy first fix produced catastrophic forgetting
  (+64.4pt on Fuzzers but general FPR exploded to 65%), and the final,
  correct, authoritative result is **21.3% → 58.3% (+36.98pt)** with
  general FPR only moving 12%→22.5%. **Use the §11b number, not this
  one, anywhere numbers are cited.** Fuzzers has no ToN_IoT name
  collision, so (unlike the rejected Backdoor choice) no counterpart-
  category exclusion is needed on that side.
- **Actual shard sizes** (updated after `carve_test_split()` added, see
  §11b): device1 (UNSW+holdout train)=104,606, device2 (UNSW)=65,280,
  device3 (ToN_IoT)=68,407, device4 (ToN_IoT)=110,980 (both ToN_IoT
  shards shrank ~15% from their original 80,477/130,566 once the ToN_IoT
  test split was carved out first), holdout replay set=5,455 rows,
  ToN_IoT held-out test set=31,656 rows. Output written to
  `data/processed/device{1..4}_train.csv`, `holdout_replay.csv`,
  `ton_iot_test.csv`, `vocab.json`, `scaler.json`, `central_pretrain_pool.csv`.
- **For the live demo**: sample ~50-100 rows from `holdout_replay.csv`
  rather than replaying all 5,455 — at a readable rate the full set takes
  15+ minutes.
- **Real bug caught and fixed during backbone training**: PyTorch's
  `nn.TransformerEncoderLayer` has a fused "fast path" that bypasses each
  submodule's `forward()` and reads `linear1.weight`/`linear2.weight`
  directly for a kernel call. Once those are `LoRALinear` instead of plain
  `nn.Linear`, that path would silently skip the LoRA delta entirely
  (wrong answer, not a crash) if it fully succeeded — it partially crashed
  instead, which is how this got caught. Fixed with
  `torch.backends.mha.set_fastpath_enabled(False)` at the top of
  `model/tabular_transformer.py`. Don't remove this.
- **Backbone trained** (10 epochs, central_pretrain_pool.csv, Fuzzers
  excluded): 97.6% validation accuracy. Checkpoint at
  `model/backbone_frozen.pt` (gitignored — regenerate via
  `python -m model.train_backbone` after pulling the repo, don't expect it
  to be there).

## 5. Edge nodes

- **4 EC2 instances** (not laptops/Pi — team decision). `t3.small` or
  `t3.medium`, not `t2.micro`/`t3.micro` (1GB RAM is tight once PyTorch +
  transformer + agent loop are resident).
- **Access: SSM Session Manager only.** No SSH, no inbound rules at all in
  the security group. IAM instance role needs `AmazonSSMManagedInstanceCore`.
  Public subnet (simplest — reaches SSM's public endpoints via IGW). Skip
  private-subnet VPC endpoints for ssm/ssmmessages/ec2messages unless a
  reviewer specifically pushes for zero-internet-egress; not needed for a
  demo.
- Outbound: 443 only (SSM + the API Gateway URL).
- Each instance has its **own API Gateway API key** — separate concern
  from SSM access. SSM is "you managing the box," the API key is "the
  agent proving which device it is" to the cloud.
- **Cost discipline**: stop instances between work sessions. 4×
  `t3.medium` running only during dev/demo sessions is trivially cheap;
  left running 24/7 for 12 weeks it isn't.

## 6. Cloud orchestration (AWS serverless)

Synchronous FedAvg rounds (chosen over async — with only 4 known clients,
synchronous is simpler to explain, matches textbook McMahan et al.
exactly, and gives a clean round-by-round dashboard visualization).

- **API Gateway**: `POST /update` (adapter upload), `GET /model` (pull
  latest global adapter), `POST /incidents` (defense actuator log).
- **DynamoDB `round_state`**: `{round, expected: 4, submitted: {...},
  status}` — coordination state, since Lambda itself is stateless.
- **Ingest Lambda**: on POST, save weight blob to S3
  (`updates/round{n}/{device_id}.pt`), atomically add `device_id` to
  `submitted` in `round_state`. If `submitted == expected`, invoke
  Aggregate Lambda synchronously.
- **Aggregate Lambda**: sample-size-weighted FedAvg over the round's
  blobs (`w_new = Σ(n_i·w_i) / Σn_i`), write `global/round{n+1}.pt` to S3,
  bump round counter, reset `submitted`, write round metrics to a
  `rounds` table for the dashboard.
- **EventBridge-scheduled Lambda**: straggler handling — if a round has
  been open past a timeout with ≥2 of 4 reported, aggregate with whoever's
  in rather than blocking forever (mirrors the client-dropout problem from
  Nishio & Yonetani, already in the lit review — cite it as such).
- **S3**: weight blobs + global model versions.
- IaC: **AWS SAM**, written (`cloud/template.yaml`). **Deployed
  2026-09-11** — stack `fedgrid` in `ap-south-1`. See §10 for the two bugs
  found and fixed during first deploy (DependsOn logical id, missing
  numpy dependency).
- **Design change from the original plan**: Lambda never gets PyTorch — a
  torch layer is huge for zero benefit, since the cloud side only ever
  averages numbers, it never runs the model. Adapter weights cross the
  wire as base64-encoded raw float32 arrays in plain JSON
  (`cloud/shared/serialization.py`), not `torch.save`/pickle.
  `edge_agent/comms.py` (which does have torch) is the only place that
  converts between `TabularTransformer`'s nested tensor state dicts and
  this flat wire format (`_flatten_state`/`_unflatten_state`).
- **Simplified from 2 Lambdas to inline aggregation**: rather than
  ingest_lambda invoking a separate aggregate_lambda synchronously
  (cross-Lambda invoke = extra IAM permission + latency + failure surface
  for math that takes milliseconds), `ingest_lambda` runs FedAvg inline
  via a shared `cloud/shared/aggregate.py` the moment quorum is hit.
  `aggregate_lambda` was repurposed as the EventBridge-scheduled
  straggler/timeout handler only (still calls the same shared aggregate
  function, so both trigger paths agree on what "an aggregation" means).
  4 Lambdas total: `ingest_lambda` (POST /update), `model_lambda`
  (GET /model), `incident_lambda` (POST /incidents), `aggregate_lambda`
  (scheduled straggler check).
- **Packaging**: all 4 functions use `CodeUri: ./` (the whole `cloud/`
  directory) rather than their own subfolder, because `shared/` has to be
  inside every function's deployed zip for `from shared import store` to
  resolve — CodeUri only packages what's under it. Slightly wasteful (each
  zip carries all 4 handlers) but correct and simple; a Lambda Layer would
  be the "proper" fix, unnecessary complexity at this scale. This means
  **two different import conventions exist in this repo on purpose**:
  code that runs as part of the full checkout (edge_agent/*, model/*,
  data/*) uses full dotted paths (`cloud.shared.serialization`); code
  that only ever runs inside the Lambda zip (`cloud/shared/aggregate.py`,
  all 4 `handler.py` files) uses short paths (`shared.store`) matching
  what Lambda's runtime actually sees. `cloud/shared/serialization.py`
  and `store.py` have no sibling-module imports, so they work under
  either convention unmodified.
- **Round coordination correctness**: DynamoDB `RoundStateTable` (single
  item, pk="GLOBAL") holds `round`, `latest_global_round`, `status`
  (collecting/aggregating), `submitted` (String Set), `round_started_at`.
  `try_join_round` (ADD to submitted, conditioned on round number) and
  `try_lock_for_aggregation` (optimistic lock: collecting→aggregating,
  conditioned on round+status) both use DynamoDB conditional updates —
  exactly one caller wins if two devices complete a round at nearly the
  same instant, or if a straggler timeout fires right as quorum completes.
  ingest_lambda retries once (re-fetches round state) if the round already
  advanced between its read and its join attempt.
- **Read side + accuracy metric added 2026-08-23** (needed once the
  dashboard made the gap obvious: there was no way to read rounds/incidents
  back out, and no accuracy number existed anywhere -- Lambda never runs
  the model, deliberately). Two more Lambdas: `rounds_lambda` (GET
  /rounds), `incidents_read_lambda` (GET /incidents) -- 6 Lambdas total
  now. Each device now self-reports a `local_val_accuracy` (holds out 15%
  of its own local buffer, never trained on, evaluated after retraining --
  `edge_agent/trainer.py`'s `LocalTrainer.last_val_accuracy`) alongside
  its adapter upload; `shared/aggregate.py` computes the sample-weighted
  average across a round's contributors and `store.complete_round` saves
  it to the Rounds table. **Call this "federated validation accuracy" everywhere it's
  shown, never "test accuracy"** — it's client-reported and sample-weighted,
  not an independent global held-out evaluation, since the cloud can't run
  the model itself. The dashboard's accuracy chart, its subtitle text, and
  this note all say so explicitly on purpose — don't let that framing
  drift in later edits.
- **Verified 2026-08-23, without touching AWS**: (1) all 6 handler files
  parse and, more importantly, *import cleanly* using the exact
  `shared.*`-style short imports Lambda's runtime will actually use
  (tested by adding `cloud/` to `sys.path` and importing each handler
  module directly, with dummy env vars). (2) The full
  flatten→encode→decode→unflatten round-trip was run against the **real
  trained `backbone_frozen.pt` adapter state** — bit-exact (0.0 max diff).
  (3) `weighted_average` was checked against the hand-computed FedAvg
  formula on real adapter tensors — correct to float32 precision (~1e-7).
  **Not verified**: the actual DynamoDB conditional-update expressions and
  the SAM template's CloudFormation resource wiring (particularly the
  `DependsOn: FedGridApiDemoStage` logical-id guess for the API key/usage
  plan resources) — these need `sam validate`/`sam build`/`sam deploy`
  against a real AWS account, which hasn't happened. Expect to fix small
  things on the first deploy attempt.
- Demo timing: compress round timeout / poll interval / local epochs to
  single-digit seconds for the live demo; note in the report that a real
  deployment would use minutes-to-hours.

## 7. Model

- **Frozen shared backbone**: Tabular Transformer (continuous-feature
  projection + categorical embeddings as tokens, small self-attention
  encoder), pretrained once, centrally, offline — **excluding the
  hold-out attack category entirely** (§4) — then frozen and shipped
  identically to all 4 devices at deployment.
- **LoRA adapters**: only the feed-forward projections inside each
  encoder block (+ the classification head) are trainable. This is what's
  actually federated — small payload, fast local fine-tune, matches the
  Muthuswamy et al. LoRA precedent already in the lit review.
- **Contrastive Adversarial Training**: local retraining combines clean
  loss + loss on FGSM-perturbed inputs, per Objective 4.
- Implemented in `model/tabular_transformer.py` + `model/lora_adapter.py`
  (built, see §9). `model/train_backbone.py` (central pretrain, must
  exclude hold-out class) not yet written — needs real data first.

## 8. Demo script

1. Baseline dashboard: Round N, decent accuracy on normal validation
   traffic, model has never seen the hold-out class.
2. Replay held-out attack set at Devices 2–4 → logged as **missed**
   (benign, high confidence) — explicit, timestamped "before" evidence.
3. Device 1's local self-eval trigger fires (deterministic — it has this
   class in its own labeled buffer) → local retrain → upload.
4. Round completes (all 4 report, or straggler-timeout with fewer) →
   Aggregate Lambda runs FedAvg → new global adapter in S3.
5. Devices 2–4 pull it on next poll.
6. Replay the **held-out replay set** (different instances than Device 1
   trained on) at Devices 2–4 → now flagged malicious, high confidence →
   defense actuator blocks + logs on all three, despite never having seen
   this attack's raw data.
7. Close on the accuracy/F1 curve stepping up at that round.

Two trigger types, used deliberately differently:
- **Reliable** (`LocalSelfEvalTrigger` in `drift_monitor.py`): Device 1
  periodically re-scores its own labeled buffer; deterministic, this is
  what the live demo depends on.
- **Autonomous** (`StreamDriftMonitor`): sliding-window confidence
  monitor on the live unlabeled stream — the interesting citable
  mechanism (compare directly against AISAF's fixed 512-sample batching
  in the report), shown as corroborating log evidence, not depended on
  for the live demo's timing.

Traffic simulation: CSV-replay of held-out rows into the agent's local
inference loop at a fixed rate — deterministic, no live-demo risk. Real
packet crafting via scapy/pyshark is an optional cosmetic bonus only, not
on the critical path.

## 9. Repo layout (as built so far)

```
data/
  raw/            # user drops UNSW-NB15 + ToN_IoT CSVs here (gitignored)
  processed/      # per-device shards + holdout replay set (gitignored)
  scripts/
    partition_data.py   # canonical mapping (placeholder columns) + Dirichlet
                         # split + hold-out carve-out. NEEDS real CSV headers.
model/
  lora_adapter.py        # LoRALinear: frozen base + trainable low-rank A/B
  tabular_transformer.py # backbone + LoRA-wrapped FFN + adapter (de)serialize
                          # (also disables torch's transformer fast-path, see §4)
  train_backbone.py      # central pretrain, excludes hold-out class, freezes backbone
  validate_holdout.py    # proves the before/after hold-out premise on real data
  backbone_frozen.pt     # gitignored checkpoint -- regenerate, don't expect it in git
edge_agent/
  agent.py          # EdgeAgent: perceive/decide/act/reflect -- the agentic core
  drift_monitor.py  # StreamDriftMonitor (autonomous) + LocalSelfEvalTrigger (reliable)
  trainer.py         # local LoRA fine-tune + contrastive adversarial (FGSM) loss
  actuator.py         # blocklist / iptables (simulate=True off Linux)
  comms.py             # HTTPS client: upload adapter, poll global model, report incident
  inference.py          # SchemaEncoder (vocab+scaler) + InferenceModel facade
cloud/
  template.yaml          # SAM: API Gateway + 6 Lambdas + DynamoDB x3 + S3 + per-device API keys
  shared/
    serialization.py     # base64 float32 wire format + weighted_average (torch-free)
    store.py              # DynamoDB/S3 boto3 wrappers, round-coordination primitives,
                          # _to_native()/_to_dynamo() Decimal boundary (see §11d)
    aggregate.py           # FedAvg trigger logic shared by ingest + straggler paths
  ingest_lambda/          # POST /update -- save weights, join round, aggregate if quorum hit
  model_lambda/           # GET /model -- latest global adapter, 204 if nothing newer
  incident_lambda/        # POST /incidents -- write-through to DynamoDB
  incidents_read_lambda/  # GET /incidents -- dashboard's live feed
  rounds_lambda/          # GET /rounds -- dashboard's accuracy chart
  aggregate_lambda/       # EventBridge-scheduled straggler/timeout handler
  local_simulation.py     # runs all 6 handlers for real against moto-mocked AWS with
                          # 4 independent devices -- see §11d, this is what proved the
                          # federated PROCESS (not just its ingredients) actually works
                          # NOT DEPLOYED to real AWS -- see §6 for what's verified vs not
run_edge_node.py         # entrypoint that actually runs on the 4 EC2 boxes --
                          # wires EdgeAgent + tools together against the real
                          # deployed API, env-var configured, see §11g.
dashboard/               # React + Vite + Recharts, built and verified (`npm run build` succeeds)
  src/api.js              # GET /rounds, GET /incidents only -- dashboard never writes
  src/mockData.js          # fallback data + loud "DEMO DATA" banner when API unreachable
  src/App.jsx               # polls every 5s, falls back to mock data on any fetch failure
  src/components/           # StatusHeader, AccuracyChart, DeviceContributions, IncidentFeed
```

## 11e. Rejected: pushing Fuzzers recovery above 90% (2026-08-23)

User asked whether the federated Fuzzers-recovery number (36.77%, §11d)
could be pushed above 90% "so it's proper." **Explicitly rejected as a
target, not just left undone** — reasoning, so this doesn't get
re-litigated without cause:

- This metric specifically measures recovering a class only ONE of 4
  devices has ever seen, after one local round. A 90%+ result would mean
  one federated round essentially solved zero-day detection outright —
  not credible for any real IDS, and a panel member who understands the
  problem reads a suspiciously perfect number as scripted. This is the
  same reasoning that already rejected "Backdoor" as the hold-out class
  (97.5% zero-shot, no room to show improvement, looked fake) — pushing
  Fuzzers to 90%+ recreates that exact problem in reverse.
- Mechanically capped anyway: even Device 1 training ALONE (undiluted by
  FedAvg) only reached 73.9% (§11b) without breaking general performance.
  Pushing harder was already tried once and produced catastrophic
  forgetting (65% FPR, §11b) — worse for the report than a modest number.
- **Where a genuine >90% number already exists, if that's the actual
  need**: general detection accuracy is legitimately strong --
  ToN_IoT 98.9%, UNSW-NB15 87.3% (§11b/§11d). Lead the report with these
  for an "impressive number," and let the Fuzzers-recovery figure do its
  actual job (demonstrating the *mechanism*), not double as a headline
  accuracy stat.

**Next step, agreed but NOT YET RUN**: give Device 1 progressively more
real, previously-untouched Fuzzers rows across additional federated
rounds (simulating it encountering more traffic over time), instead of
retraining on the same static 12,729-row slice every round the way
`cloud/local_simulation.py` currently does. Constraints for whoever picks
this up:
- **Never touch `holdout_replay.csv` (5,455 rows) or the UNSW official
  test file's Fuzzers rows (6,062 rows, inside `unsw_nb15_test.csv`)** --
  both must stay genuinely held-out for evaluation. Any additional
  training rows have to come from data not already used anywhere in the
  pipeline, which likely means re-partitioning with a smaller
  `replay_fraction` in `carve_holdout_set()` (`data/scripts/
  partition_data.py`) to free up more Fuzzers rows for Device 1's
  training slice while still keeping a smaller-but-genuine replay set --
  or accept a smaller held-out eval set as the tradeoff.
- Realistic expectation set going in: **40–60% range with diminishing
  returns, not 90%+.** If a run comes back near 90%, treat that as a bug
  to investigate (most likely eval-set contamination), not a win to
  report uncritically -- same discipline as catching the catastrophic-
  forgetting and Decimal bugs earlier in this session.
- Re-use `cloud/local_simulation.py`'s structure (it already proves the
  multi-device round mechanics work) -- extend it to run more rounds with
  Device 1's buffer growing round-over-round, rather than writing a new
  harness from scratch.

## 11f. Multi-round progressive Fuzzers experiment — run (2026-09-10)

The §11e plan (agreed 2026-08-23, not run until now) is complete:
`cloud/multiround_fuzzers_experiment.py`, structurally based on
`cloud/local_simulation.py` (same real Lambda handlers + moto-mocked AWS),
reveals Device 1's existing 12,729-row Fuzzers training pool
**progressively** across 4 rounds (25/50/75/100% cumulative) instead of
all at once, and tracks the GLOBAL (FedAvg-averaged) model's Fuzzers
recall after each round. Devices 2-4 keep their normal static buffers.

**Simpler than the §11e plan anticipated, and correct**: no re-carving of
`holdout_replay.csv` or the official test file was needed -- the
progressive tranches came entirely out of Device 1's *already-allocated*
12,729-row pool (`device1_train.csv`, filtered by `attack_cat=="Fuzzers"`),
just revealed gradually. Both held-out eval sets (`holdout_replay.csv`,
5,455 rows; official `unsw_nb15_test.csv` Fuzzers subset, 6,062 rows)
stayed **completely untouched by training**, exactly as before -- the
"re-partition with a smaller replay_fraction" fallback in §11e turned out
to be unnecessary.

**Real, measured result** (global model, evaluated on device2, which never
sees Fuzzers locally):

| round | cum. Fuzzers revealed | official-test Fuzzers recall | replay-set Fuzzers acc | general acc | general FPR |
|---|---|---|---|---|---|
| 0 (before) | 0% | 36.44% | 23.15% | 87.29% | 12.53% |
| 1 | 25% | 40.25% | 28.45% | 87.32% | 13.70% |
| 2 | 50% | 45.53% | 35.33% | 63.89% | 18.04% |
| 3 | 75% | 51.91% | 42.64% | 85.66% | 20.10% |
| 4 | 100% | **58.61%** | **51.44%** | 84.84% | 23.24% |

Both Fuzzers metrics climb smoothly and monotonically with more exposure
(+22.17pt official-test, +28.29pt replay-set) -- lands squarely in the
40-60% range §11e predicted going in, **not** the suspicious 90%+ zone
that was explicitly rejected as a target (§11e) -- a real sanity check
passed, not just a hoped-for number. FPR keeps climbing with more Fuzzers
exposure, same precision/recall tradeoff pattern already disclosed in
§11b/§11d.

**Anomaly found and flagged, not hidden**: round 2's general accuracy
transiently collapsed to 63.89% (from 87.32%) before recovering to 85.66%
by round 3. Not seen in the earlier 2-round experiment (§11d, which only
ran 2 rounds and never dipped) -- this surfaces a genuinely NEW limitation
under 4+ rounds: devices 2-4 retrain every round starting from the
*previous round's already-FedAvg'd* global model rather than the frozen
backbone, so LoRA drift can compound round-over-round even with static
local buffers. Plausible real client-drift instability, not confirmed as
a bug -- **not yet re-run with a different seed to confirm
reproducibility**. Don't cite the round-2 number specifically in the
report without a repeat run; the round-4 headline number (58.61% /
51.44%) is unaffected either way since it's measured after recovery.

**Use for the report**: this progressive-exposure framing is a better zero-
day-recovery story than a single round -- it demonstrates recovery
*rate*, not just a single before/after snapshot, and the smooth monotonic
climb is more defensible in front of a jury than one big jump. The
compounding-drift anomaly at round 2 is itself a legitimate limitations-
section point (cite it as an open question, not swept under the rug).

**Next step, not yet run**: repeat with a different `SHUFFLE_SEED` (and
maybe different `CUMULATIVE_FRACS`) to check whether the round-2 dip
reproduces or was a one-off from that particular random hard-example
sampling draw.

**Seed-variation re-run — done (2026-09-14), dip does NOT reproduce**:
`SHUFFLE_SEED=456` (vs. the original 123), same 4 rounds, same real
Lambda handlers + moto-mocked AWS, nothing else changed:

| round | cum. Fuzzers revealed | official-test Fuzzers recall | replay-set Fuzzers acc | general acc | general FPR |
|---|---|---|---|---|---|
| 0 (before) | 0% | 36.44% | 23.15% | 87.29% | 12.53% |
| 1 | 25% | 37.66% | 26.14% | 87.71% | 12.06% |
| 2 | 50% | 48.33% | 37.89% | 85.84% | 19.12% |
| 3 | 75% | 48.15% | 38.28% | 85.69% | 18.99% |
| 4 | 100% | **64.42%** | **58.33%** | 84.09% | 26.57% |

General accuracy declines **monotonically** across all 4 rounds
(87.71%→85.84%→85.69%→84.09%) with no dip-then-recover pattern — the
seed-123 round-2 collapse-to-63.89%-then-recovery (§11f) is confirmed to
be **a one-off artifact of that specific hard-example sampling draw, not
a reproducible compounding-drift bug**. Both Fuzzers metrics again climb
monotonically and land in a similar range to the seed-123 run (+27.98pt
official-test, +35.18pt replay-set here vs. +22.17pt/+28.29pt with seed
123) — consistent story, not seed-dependent luck. FPR climbs steadily
with no anomalous spike either. `SHUFFLE_SEED` reverted to `123` in
`cloud/multiround_fuzzers_experiment.py` afterward (kept as the canonical
documented seed for the headline §11f numbers) — this run's script diff
was seed-only, no other changes.

**Conclusion for the report**: cite the seed-123 numbers as the headline
progressive-recovery result (§11f), and this seed-456 re-run as the
robustness check — safe to say the monotonic Fuzzers-recovery trend is
real and seed-independent; the round-2 general-accuracy dip specifically
was noise from one sampling draw, not a limitation worth a paragraph in
the report (downgrade it from "open question" to "checked, doesn't
reproduce").

## 10. Open TODOs / pending decisions

- [x] Download UNSW-NB15 + ToN_IoT — done 2026-08-23, both direct SharePoint
      downloads off the official UNSW project pages, no registration
      needed. Files live in `data/raw/` (see §4 for exact filenames).
      **Citation requirement is mandatory**: UNSW-NB15 requires citing 5
      specific papers, ToN_IoT requires citing 8 — both listed on their
      project pages. Add to the report's reference list, separate from the
      5 papers already in the lit review section.
- [x] Schema mapping + hold-out design — done, verified against real
      headers, `partition_data.py` runs end to end (§4 has the full list
      of things that turned out different from the original guess — read
      it before touching this script).
- [x] `model/train_backbone.py` — done, trained, 97.6% val accuracy. Run
      `python -m model.train_backbone` to regenerate
      `model/backbone_frozen.pt` (gitignored, not committed).
- [x] `edge_agent/inference.py` — done (`SchemaEncoder` + `InferenceModel`
      facade). `EdgeAgent.perceive()`'s `model.infer(flow_record)` call now
      resolves correctly when `self.model` is an `InferenceModel`.
- [x] `model/validate_holdout.py` — done, this is what proved the Fuzzers
      hold-out choice for real. Rerun it any time the hold-out class,
      dataset split, or backbone training changes — it's the fastest way
      to catch a broken demo premise before touching AWS/EC2.
- [x] AWS: SAM template + 6 Lambdas + DynamoDB tables + S3 bucket + API
      Gateway with per-device usage-plan keys — **deployed 2026-09-11**,
      stack `fedgrid` in `ap-south-1`, under IAM user `FEDGRID-DEPLOY`
      (not root). Fixed the `DependsOn` logical-id bug found by
      `sam validate --lint`: the real generated id is
      `FedGridApidemoStage` (lowercase "demo"), not `FedGridApiDemoStage`
      as originally guessed — template.yaml corrected. Also added
      `cloud/requirements.txt` (`numpy`) which was missing — `shared/
      serialization.py` uses `np.asarray`/`np.frombuffer` for real at
      runtime, so `ingest_lambda`/`aggregate_lambda` would have thrown
      `ImportError` on first invocation without it. Built via SAM's local
      pip builder using a side-by-side Python 3.12 install (host had only
      3.14) — confirmed the bundled numpy wheel is the Linux
      `cp312-x86_64-linux-gnu` build, not Windows binaries. Smoke-tested
      post-deploy: `GET /rounds` → `{"rounds": []}` (200), `GET /model` →
      204, both authenticated with a device API key. `dashboard/.env.local`
      now points at the live API (gitignored, key not committed).
      **StragglerFunction's EventBridge schedule (rate(1 minute)) is now
      live and runs continuously** — set `Enabled: false` and redeploy, or
      `sam delete --stack-name fedgrid`, once the demo/report is done, so
      it doesn't run indefinitely.
- [x] EC2 provisioning + SSM setup for the 4 nodes — **done 2026-09-11**,
      see §11g for instance IDs and what happened.
- [x] Push edge code onto the 4 EC2 nodes + wire real API keys — **done
      2026-09-14**, see §11g "Code deployed and running for real" for the
      two real bugs hit (missing requirements.txt, tmpfs-too-small torch
      install) and the DynamoDB-scan proof it's genuinely working end to
      end. Instances left running after this — stop them when done.
- [x] Multi-round Fuzzers-recovery experiment — run 2026-09-10, see §11f.
      Real result: official-test Fuzzers recall 36.44%→58.61% (+22.17pt)
      across 4 progressive rounds, replay-set 23.15%→51.44% (+28.29pt),
      both in the predicted 40-60% range (not suspicious 90%+). Found and
      flagged (not hidden) a transient round-2 general-accuracy dip
      (87.3%→63.9%→85.7% recovery) — plausible compounding client drift
      over 4+ rounds, NOT yet confirmed reproducible with a different seed.
      `cloud/multiround_fuzzers_experiment.py`.
- [x] Re-run the multi-round Fuzzers experiment with a different
      `SHUFFLE_SEED` — done 2026-09-14, dip does NOT reproduce (monotonic
      decline instead), confirmed a one-off sampling artifact, not a real
      bug. See §11f addendum for the full seed-456 table.
- [x] React dashboard — built, `npm run build` verified clean
      (dashboard/dist/, gitignored). Falls back to labeled mock data if
      the API isn't reachable, so it's previewable now (`npm run dev`)
      even before the cloud stack is deployed. Needs `dashboard/.env.local`
      (from `.env.example`) with real `VITE_API_BASE_URL`/`VITE_API_KEY`
      once `sam deploy` has actually happened.
- [x] Explainability dashboard piece (Objective 5, attention-rollout) —
      built (`model/explain.py`), wired end to end into `agent.py` →
      `actuator.py` → incident payload → dashboard `AttentionBar.jsx`.
      See §11c.
- [x] Missing evaluation metrics (Precision/Recall/Macro F1/FPR/DRI/
      latency/payload size) — built (`model/evaluate.py`) and run for
      real against genuine held-out data. See §11b for the numbers.
- [x] Local-training dilution + catastrophic-forgetting bug — found,
      fixed, and re-verified with real before/after numbers on the full
      82K-row test set. See §11b.
- [x] ToN_IoT independent held-out evaluation gap — closed 2026-08-23,
      `carve_test_split()` added, `data/processed/ton_iot_test.csv`
      (31,656 rows) now exists and is evaluated. See §11b for numbers
      and the cross-dataset-FPR finding this surfaced. **Current
      authoritative Fuzzers number**: 23.2%→73.9% (+50.7pt), DRI 0.66 --
      supersedes the earlier 21.3%→58.3% figure (backbone was retrained
      on the updated pretrain pool composition).
- [x] Decide exact `d_model`/`n_heads`/`n_layers` for the transformer —
      stale checkbox, already resolved in practice: `d_model=32,
      n_heads=4, n_layers=2` (`model/tabular_transformer.py`) is what
      `backbone_frozen.pt` was actually trained, evaluated (§11b/§11d),
      and deployed with. Closed out 2026-09-14, no architecture change
      needed.

## 11a. Literature/objective alignment audit (2026-08-23) and fixes in progress

Ran a full honesty pass against the synopsis's own lit review + objectives
+ evaluation metrics. Findings and what's been done about each:

- **XGBoost rejection**: was already decided in the synopsis (citing
  Muthuswamy et al.), not a decision made during this build. The stated
  reason ("Transformers are inherently better at subtle payloads than
  trees") is weak/arguable — a fair amount of ML literature finds
  gradient-boosted trees beat transformers on tabular data generally. The
  actually-defensible reason: XGBoost has no LoRA-adapter equivalent (not
  parameterized as continuous weight matrices), so a neural architecture
  was close to a requirement given the LoRA-based federation design, not
  just a quality preference. **If rewriting the report, use this
  justification instead of the synopsis's original one.**
- **mitmproxy**: named in the synopsis (Vijetha comparison + methodology
  stack) but **used nowhere in this codebase** — dropped when scope
  narrowed to network-level-only. Don't claim it in the report without
  either building it or removing the claim.
- **"Zero-knowledge orchestrator"**: wrong term. Zero-knowledge is a
  specific cryptographic technique (ZK proofs), not used here. What's
  actually built is "cloud never sees raw data" — a privacy property, not
  a zero-knowledge one. Fix this wording before the report goes out;
  a security-literate reviewer will ask "which ZK protocol" otherwise.
- **"Sequential anomaly detection"**: the model attends over one flow's
  *features* (4 tokens), not a *sequence of flows over time*. Not
  temporal/sequential in any real sense — don't oversell this word.
- **Vijetha/AISAF comparison**: our drift trigger is real (sliding-window
  confidence, not fixed-batch) but AISAF's actual technique is
  *latent-space deviation*; ours only watches softmax confidence, not
  internal embeddings. Partial match, not a full one.
- **Objective 5 (explainability/attention-rollout)**: was entirely
  unbuilt — **now built**, see §11b.
- **Evaluation metrics**: synopsis promises Accuracy, Precision, Recall,
  Macro F1, False Positive Reduction Rate, Drift Recovery Index, Inference
  Latency, Payload Size. Only accuracy had ever been measured, and only
  via an internal 15% split (the real `unsw_nb15_test.csv`, 82,332 rows,
  sat downloaded and completely unused — confirmed via grep, zero
  references anywhere). **Now fixed**, see §11b — `model/evaluate.py`
  measures all of these against the genuine held-out test file.

## 11b. Local-training dilution bug, hard-example-mining fix, and the honest numbers

Prompted by re-testing "is this actually correct" rather than trusting the
first isolated-slice result:

- **The bug**: `validate_holdout.py`'s original +15.2-point result (21.3%
  → 36.5%) trained on an artificially clean slice — ONLY Device 1's
  Fuzzers rows (12,729), zero benign examples mixed in. Testing against
  Device 1's actual, realistic full local buffer (104,606 rows, 88% other
  traffic) with the OLD full-batch-single-step trainer dropped the result
  to only +5.7 points (21.3% → 27.0%) — full-batch gradient descent over
  a heavily diluted buffer barely moves the needle on the 12% that's
  actually relevant. This is dilution, not overfitting — a real,
  measured effect, not a hypothetical one.
- **The fix**: `edge_agent/trainer.py` rewritten — mini-batched (batch
  size 64) with **online hard-example-weighted sampling**: before every
  epoch, weight each local example by the model's current loss on it and
  sample minibatches proportionally. Needs no attack-category label, only
  the binary label real local data would have. Class default epochs
  bumped from 3 to 5 to match what's actually been validated.
- **First attempt at the fix produced catastrophic forgetting, measured
  and rejected**: uncapped hard-example weighting with `steps_per_epoch =
  n // batch_size` scaled to ~1,634 steps/epoch × 5 epochs = ~8,170 total
  gradient steps on the 104K-row buffer (not a lightweight LoRA nudge, a
  full retraining run). Result: general test accuracy collapsed 86.9% →
  50.3%, Macro F1 0.868 → 0.484, **false positive rate exploded 12% →
  65.4%** (flags two-thirds of legitimate traffic as malicious), while
  Fuzzers replay accuracy hit 86.7%. Caught by deliberately checking
  general-traffic performance before accepting the good-looking Fuzzers
  number, not assumed safe.
- **Fixed properly**: `steps_per_epoch` is now a FIXED constant (default
  20, independent of buffer size) — `epochs × steps_per_epoch` is the
  entire step budget no matter how large a device's local buffer is.
  Sampling weights are clipped (`max_loss_weight=3.0`) and floored
  (`weight_floor=0.3`) so the hardest/easiest sampling ratio stays
  bounded (~11x) instead of unbounded.
- **FINAL, authoritative result** (full 82,332-row UNSW-NB15 held-out
  test set + full 5,455-row Fuzzers replay set, batched evaluation, fixed
  trainer, 100 total steps, 7.8s retrain):

  | metric | before | after |
  |---|---|---|
  | general accuracy | 86.92% | 85.14% |
  | general macro F1 | 0.8683 | 0.8478 |
  | general false positive rate | 12.00% | 22.51% |
  | **Fuzzers recall (headline demo number)** | **21.32%** | **58.30%** (+36.98pt) |

  Drift Recovery Index (our proxy, see below): **0.4699**. This
  **supersedes both earlier numbers** (+15.2pt from the artificially clean
  isolated-Fuzzers-only test, and +5.7pt from the diluted full-batch
  attempt) — use +36.98pt / 21.3%→58.3% as THE number going forward.
  **Real, disclosed tradeoff**: FPR nearly doubled (12%→22.5%) in exchange
  for the recall gain — a genuine precision/recall tradeoff, not a defect
  to hide. Worth a paragraph in the report's limitations section: more
  false alarms vs. catching more real attacks, a real security-team
  concern (alert fatigue) that a production deployment would need to
  tune further.
- **`predict_all()` in `model/evaluate.py` was fixed to be batched**
  (was one Python-level forward pass per row — took several minutes over
  82K rows purely from call overhead, not model compute; batched version
  does the full set in 4.4s). `measure_latency()` deliberately stays
  row-by-row — it's measuring real single-flow inference latency, which
  is what the live agent actually does per flow, not a throughput number.
- **`model/evaluate.py` built and run for real** — all the promised
  metrics now have actual numbers (see table above): Accuracy, Precision,
  Recall, Macro F1, False Positive Rate, Inference Latency (median 1.03ms,
  p95 1.57ms — comfortably under the synopsis's sub-50ms target), Adapter
  Payload Size (14.27 KB — small, supports the communication-efficiency
  claim). Also defines `drift_recovery_index()` = 0.4699 — **our own
  proxy metric**, `(after-before)/(1-before)`, explicitly NOT claimed to
  match Vijetha/AISAF's undisclosed exact DRI formula (their paper wasn't
  detailed enough in the reviewed excerpt to replicate it precisely).
  **Gap closed 2026-08-23**: `data/scripts/partition_data.py` now has
  `carve_test_split()` — a genuine, stratified 85/15 train/test split for
  ToN_IoT (mirroring what UNSW-NB15 gives for free), carved AFTER
  vocab/scaler are built (full value space) but BEFORE anything trains,
  same ordering discipline as the earlier vocab bug. Output:
  `data/processed/ton_iot_test.csv` (31,656 rows, never touched by
  central pretraining or Devices 3/4's local data). Backbone was
  retrained on the updated (slightly smaller) pretrain pool; Device 3/4
  shard sizes shrank proportionally (68,407 / 110,980, down from
  80,477 / 130,566). `model/evaluate.py` now evaluates both datasets
  independently -- see the results table below.

  **Frozen global model, both datasets, genuinely held out**:

  | | UNSW-NB15 (82,332 rows) | ToN_IoT (31,656 rows) |
  |---|---|---|
  | accuracy | 87.29% | **98.93%** |
  | macro F1 | 0.8719 | 0.9851 |
  | false positive rate | 12.53% | **2.93%** |
  | Fuzzers recall (UNSW only, official test split, 6,062 rows) | 36.44% | -- |

  ToN_IoT is dramatically easier to detect than UNSW-NB15 -- consistent
  with the earlier candidate-testing finding (injection/xss were ~99%
  zero-shot). Confirms, doesn't contradict, prior findings.

  **After the backbone retrain, Fuzzers hold-out story re-validated**
  (fresh backbone, 16.5s local retrain, 100 steps): demo replay set
  (`holdout_replay.csv`, 5,455 rows) went **23.2% → 73.9% (+50.7pt)** --
  larger than the prior backbone's +36.98pt, and DRI is now 0.66 (up from
  0.47). **This is now the current authoritative number, superseding the
  §11b table above** -- re-derive again if the backbone or trainer changes.
  Two different "Fuzzers before" numbers exist and are BOTH valid, not
  contradictory: 36.44% (official UNSW test file's Fuzzers rows, 6,062)
  vs. 23.2% (our own hand-carved `holdout_replay.csv`, 5,455 rows, drawn
  from the train file) -- different row pools, both genuinely untrained-on.

  **New finding, not a bug -- a real limitation to report honestly**:
  after Device 1's retrain, general FPR moved 12.5%→25.1% on UNSW
  (~2x) but 2.9%→**27.6%** on ToN_IoT (**~9.4x**) -- even though Device 1
  never saw a byte of ToN_IoT data. Its local buffer is 100%
  UNSW-flavored; pulling the ONE shared LoRA adapter toward UNSW patterns
  costs ToN_IoT-side calibration disproportionately. Genuine limitation of
  one shared adapter across heterogeneous device types (enterprise vs.
  IoT traffic) -- worth a paragraph in the report's future-work section
  (e.g. per-source-domain adapter conditioning), not something silently
  patched over.

  Latency in this run measured higher (mean 2.59ms vs. the earlier
  1.03ms median) -- likely system load from this session's accumulated
  background processes, not a real model change (architecture is
  identical); still comfortably under the 50ms target either way, don't
  read too much into the exact latency number without a clean re-measure.

## 11c. Attention-rollout explainability (Objective 5) — built

- `model/explain.py`: `attention_rollout(model, x_cont, x_cat)` —
  Abnar & Zuidema (2020) attention rollout, adapted for 4 tokens
  (continuous features, proto, service, state), no CLS token. Recomputes
  attention explicitly via each encoder layer's `self_attn` submodule
  directly (`need_weights=True`) rather than hooking `forward()`, because
  `nn.TransformerEncoderLayer` calls `self_attn` internally with
  `need_weights=False` by default (same fast-path category of gotcha as
  the LoRA fix in `tabular_transformer.py`). Smoke-tested standalone:
  output sums to 1.0, sensible distribution across tokens.
- Wired into `edge_agent/agent.py`: `EdgeAgent.act()` now takes
  `flow_record` and calls a new `_explain()` helper on every BLOCK/ALERT,
  computing the rollout and attaching it to the incident. Best-effort —
  wrapped so a failure never blocks the actual detection/defense action.
- `edge_agent/actuator.py`'s `log_incident()` takes an `explanation` param
  and includes it as `entry["attention"]` when present — flows through
  `comms.report_incident` → `POST /incidents` → DynamoDB unchanged (nested
  maps are native DynamoDB, no schema change needed cloud-side).
- Dashboard: new `AttentionBar.jsx` component renders a proportional
  stacked bar per incident (color-coded by token); wired into
  `IncidentFeed.jsx` as a new "Why" column. Mock data updated with example
  attention distributions. **Rebuilt and verified** (`npm run build`
  succeeds after these changes).
- Explicitly a heuristic attribution, not a causal proof — every place
  this is surfaced (code docstring, dashboard subtitle) says so on
  purpose; don't let a stronger claim creep in later.

## 11d. Full multi-device federated process — proven, not just asserted (2026-08-23)

Every test before this ran ONE device, ONE script, sequentially. This is
the first time the actual federated PROCESS -- multiple independent
devices coordinating through the cloud -- was ever run, anywhere,
including local simulation. Built `cloud/local_simulation.py`: runs 4
genuinely independent device models against the REAL
`cloud/shared/store.py`, `aggregate.py`, and all 6 Lambda handler
functions (imported and called directly, not reimplemented), backed by
`moto`-mocked DynamoDB + S3 -- real conditional-expression semantics,
real S3 object storage, no AWS billing or credentials needed. Deliberately
does NOT test the API Gateway HTTP layer itself (routing, API key auth,
CORS) -- that genuinely needs real AWS, tomorrow. Everything downstream
of API Gateway is exercised for real.

**Bug found on first run, would have broken the real AWS deployment
too**: DynamoDB's resource-level boto3 API returns every Number attribute
as `Decimal`, not `int`/`float` -- `json.dumps()` can't serialize
`Decimal`, so the very first Lambda response crashed. Not a moto quirk --
standard, well-known DynamoDB/boto3 behavior. Fixed at the source:
`store.py` now has `_to_native()` (Decimal → int/float, applied to every
DynamoDB read) and `_to_dynamo()` (float → Decimal, applied to every
DynamoDB write) so nothing outside `store.py` ever has to know DynamoDB
exists. Re-ran clean after the fix.

**Full run result, all real Lambda code**:
- Round 1: all 4 devices retrain independently + upload via real
  `ingest_lambda`; quorum correctly detected at the 4th submission,
  auto-aggregated, round advanced 1→2.
- Round 2: same pattern, correct again.
- Round 3 (straggler test): only 2/4 devices reported; simulated timeout
  elapsed; scheduled `aggregate_lambda` (straggler handler) correctly
  force-aggregated with just 2/4.
- Incident round trip: `incident_lambda` (write) → `incidents_read_lambda`
  (read), attention-rollout data survived DynamoDB's nested-map storage
  intact.

**Critical correction to the headline demo number** -- this supersedes
everything in §11b:

| | Fuzzers replay accuracy |
|---|---|
| before any round | 23.15% |
| after round 1 (**real global model, averaged across all 4 devices**) | **36.65%** |
| after round 2 (global model) | 36.77% |

The §11b number (23.2%→73.9%, +50.7pt) was Device 1's SOLO local model,
never actually averaged with the other 3 devices' updates. Once genuinely
run through FedAvg with Devices 2/3/4 (whose updates are not
Fuzzers-focused), their weight dilutes Device 1's specific improvement.
**The real federated result is +13.5 points (23.15%→36.65%), not
+50.7 points.** Both numbers are real measurements, but only +13.5pt is
what "federated" actually means -- **use this as the authoritative demo
number from here forward, not the §11b figure.** This is exactly the kind
of gap that only running the actual multi-device process (not testing
components in isolation) can catch -- worth remembering as a general
lesson, not just for this number.

Round 1→2 barely moved (36.65%→36.77%) because devices retrain on the
same static local buffer each round in this simulation -- a real
deployment would have new/changing traffic between rounds, so don't read
"federated learning plateaus after one round" into this; it's an artifact
of the simulation re-deriving a similar gradient from unchanged data, not
a property of FedAvg itself.

## 11g. EC2 edge-node provisioning — done (2026-09-11)

All 4 edge nodes are provisioned and confirmed working, matching the §5
design exactly:

- **IAM role `fedgrid-edge-node-role`** (instance profile
  `fedgrid-edge-node-profile`, `AmazonSSMManagedInstanceCore` only) and
  **security group `fedgrid-edge-node-sg`** (zero ingress rules, egress
  restricted to tcp/443 → 0.0.0.0/0 only) **already existed** going into
  this session, created earlier the same day (2026-09-11, timestamp
  09:08:31Z — presumably alongside the SAM deploy work, but not logged
  anywhere in this file until now). Verified both match the §5 spec
  exactly before reusing them, not recreated.
- Launched 4× `t3.small` in the default VPC (`vpc-0830257bfe6f750e1`),
  AMI `ami-0f937e388a57b1f65` (standard, non-minimal AL2023 — SSM Agent
  preinstalled), spread across AZs, no key pair (SSM-only, no SSH by
  design):

  | device | instance id | AZ |
  |---|---|---|
  | device-1 | `i-0b21c5f1e75bcf14c` | ap-south-1a |
  | device-2 | `i-044fed5739b0e043e` | ap-south-1c |
  | device-3 | `i-0f7691cd6167f261d` | ap-south-1b |
  | device-4 | `i-0d67c79d3e5805072` | ap-south-1a |

- **AWS account-level hold hit mid-launch**: after device-1/2 launched
  cleanly, device-3/4 failed with `PendingVerification` — an AWS-side
  account/region verification check (their own message: resolves in
  minutes to up to 4 hours, notified by email). Not a quota, IAM, or
  config issue — device-1/2 used the identical role/SG/AMI. Handled with
  a backgrounded retry loop (10-minute interval, 4-hour cap); cleared on
  the very first retry (~10 minutes). No manual AWS Support case needed
  in the end, but that's the fallback if it recurs and doesn't
  self-clear.
- All 4 confirmed **SSM `PingStatus: Online`** after launch — the IAM
  role + SG configuration works as designed, no fixes needed.
- **Stopped (not terminated) immediately after verification**, per cost
  discipline (§5) — instance IDs above are reusable, don't re-provision
  from scratch next session; just `aws ec2 start-instances` on these 4
  ids.

**Code deployed and running for real — done (2026-09-14)**. What actually
happened, since it took a few real bugs to get here:

- **`run_edge_node.py` (new, repo root) had to be written first** — no
  script anywhere actually wired `EdgeAgent` + its tools (model, trainer,
  drift monitors, actuator, `CloudComms`) into a running process against
  the real API. Every prior script (`cloud/local_simulation.py`,
  `cloud/multiround_fuzzers_experiment.py`) only drove these pieces
  in-process against moto-mocked AWS. Env-var configured (`DEVICE_ID`,
  `API_BASE_URL`, `API_KEY`, `ROW_RATE_HZ`, `REAL_BLOCK`, optional
  `REPLAY_CSV`/`REPLAY_EVERY` to inject `holdout_replay.csv` rows into
  devices 2-4's stream for the live demo per §8) so the identical script
  runs unmodified on all 4 boxes. Replays the device's own local
  partition, shuffled, cycling indefinitely at `ROW_RATE_HZ`.
- **Per-device deploy bundles, not one shared bundle**: each of the 4
  tarballs staged to `s3://fedgrid-weightsbucket-kwh3ffbpsq5a/deploy/
  device{1..4}.tar.gz` contains only that device's own
  `device{N}_train.csv`, never the other 3 devices' data — bundling all 4
  onto every box would have undercut the project's own "device only ever
  has its own local data" privacy claim, even though nothing crosses to
  the cloud either way.
- **Real API keys never touched Claude's context or a terminal echo**:
  the sandbox correctly refused both `aws apigateway get-api-key
  --include-value` (credential materialization) and the IAM policy grant
  needed for instances to read them. Both were done by the user directly
  in their own shell: (1) an inline IAM policy on `fedgrid-edge-node-role`
  granting `ssm:GetParameter(s)` on `/fedgrid/*`, `kms:Decrypt` (via the
  default SSM-managed key), and `s3:GetObject` on the `deploy/` prefix;
  (2) each device's real key value written straight into SSM Parameter
  Store as `SecureString` (`/fedgrid/device{1..4}/api_key`,
  `/fedgrid/api_base_url` as plain `String`). The bootstrap script fetches
  these itself at install time via the instance's own role and writes
  them into a `chmod 600` env file (`/opt/fedgrid/agent.env`), not into
  the (world-readable, 644) systemd unit file.
- **Two real bugs hit and fixed during rollout**: (1) the per-device
  tarballs were first built without `requirements.txt` — `pip install -r
  requirements.txt` failed with a plain missing-file error, caught
  immediately from the SSM command's stderr. (2) `pip install torch`
  (default PyPI wheel, CUDA-bundled) failed with `OSError: [Errno 28] No
  space left on device` even though the root volume had 6GB free — `/tmp`
  on these AL2023 boxes is a small RAM-backed tmpfs (955MB on a
  `t3.small`), and pip's download temp dir lives there by default. Fixed
  by pointing `TMPDIR` at real disk (`/opt/fedgrid/tmp`) and installing
  the CPU-only wheel (`--index-url https://download.pytorch.org/whl/cpu`)
  instead of the default CUDA build — this project never touches a GPU
  anyway, and the CPU wheel is a fraction of the size.
- **Delivery mechanism**: `run_edge_node.py` runs as a systemd service
  (`fedgrid-agent.service`, `enabled` so it survives reboot,
  `Restart=on-failure`), installed via `AWS-RunShellScript` through SSM
  Run Command (no SSH exists on these boxes by design, §5) —
  `sudo systemctl status fedgrid-agent` / `sudo journalctl -u
  fedgrid-agent` / `tail -f /var/log/fedgrid-agent.log` to check any
  device from here forward. `REAL_BLOCK=0` (simulated firewall blocks,
  logged not applied) is the current default on all 4 — flip to `1` in
  `/opt/fedgrid/agent.env` + restart the service only if a demo
  specifically wants to show a real `iptables` rule land.
- **Verified working end-to-end against the real deployed API, not just
  "the install script exited 0"**: all 4 systemd services report
  `active`/`enabled`; device2's `SYNC_DOWNLOAD` action succeeded (would
  have raised on a bad/missing API key, since `fetch_global_adapter`
  calls `raise_for_status()`); confirmed by directly scanning
  `fedgrid-IncidentsTable-U5B4NPHIN3B` — **13 real incidents** landed in
  DynamoDB from live agent decisions within the first ~90 seconds of all
  4 running, proving the full EC2 → API Gateway → Lambda → DynamoDB path
  works for real, not just in `local_simulation.py`'s moto mock.
- **Cost discipline reminder (§5 still applies)**: all 4 instances were
  started for this deployment and are still running as of 2026-09-14 —
  **stop them (`aws ec2 stop-instances`) once done with this session's
  work**, the systemd service + SSM parameters + S3 bundles all persist
  across a stop/start cycle so nothing needs re-deploying next time,
  just `aws ec2 start-instances` on the same 4 ids from §11g.

## 12. LoRA base-never-trained bug — found, fixed, everything re-measured (2026-09-14)

**The bug**: `TabularTransformer.__init__` wraps the FFN sublayers
(`linear1`/`linear2`) in `LoRALinear` immediately at construction, and
`LoRALinear.__init__` freezes the wrapped base weight unconditionally,
right then — before any training loop ever runs. This meant
`model/train_backbone.py`'s "central pretraining" never touched the FFN's
base weight matrix at all, at any point in the project's history: it sat
at PyTorch's random initialization for the model's entire lifetime,
including in every checkpoint ever trained and the one live on all 4 EC2
nodes before this fix. Verified directly (not assumed):
`layer.linear1.base.weight.requires_grad` was `False` the instant a fresh
`TabularTransformer` was constructed, before `.to(device)` or any
optimizer existed. Only `cont_proj`, `cat_embeds`, `self_attn`
(un-wrapped attention projections), the FFN's `lora_A`/`lora_B`, and
`head` ever received gradients, at any stage, ever. Every number in
§4/§7/§11* was measured against this backbone.

**Why this matters, precisely**: LoRA's premise (Hu et al. 2021) is a
cheap trainable correction on top of an already-pretrained weight. Doing
that to a matrix that was never pretrained at all is closer to a fixed
random-feature projection wearing a trained low-rank correction —
different from what the citation and the "frozen pretrained backbone"
framing throughout this doc claimed. The measured accuracy numbers were
still real (the model does work), but the *description* of why it works
was wrong, and would not have survived a reviewer reading the code.

**The fix** (`model/lora_adapter.py`, `model/tabular_transformer.py`,
`model/train_backbone.py`): central pretraining now explicitly unfreezes
the FFN base (`unfreeze_ffn_base_for_pretraining()`) so it trains jointly
with the LoRA delta on the real objective. After training,
`merge_and_reset_adapters()` folds the learned delta into the base
(`base.weight += scale * lora_B @ lora_A`) and resets `lora_A`/`lora_B`
to zero-effect, THEN `freeze_backbone()` runs — the textbook
LoRA-after-pretrain workflow: adapt a real trained weight starting from a
zero delta, not a permanently-random one. Verified mechanically before
retraining: in eval mode, model output is bit-exact identical
(max diff 0.0) immediately before vs. after the merge — proves the merge
is a pure algebraic reparameterization, not a behavior change, and that
training the base pre-merge actually moved it (confirmed by diffing
`base.weight` before/after a few optimizer steps in isolation).

**Backbone retrained** (same 10 epochs, `central_pretrain_pool.csv`,
Fuzzers still excluded): 97.44% central validation accuracy (was 97.6% —
essentially unchanged, consistent with the FFN base's contribution being
secondary to attention/cont_proj/head, which were already training
correctly all along).

**Fuzzers still a valid hold-out choice, re-confirmed, not assumed**: the
"before" zero-shot state is still clearly bad (43.32% official-test
recall, up from the buggy backbone's 36.44% but still far below general
recall ~88-89% — a real generalization gap remains, just a somewhat
smaller one). Not the "already near-perfect, no room to show recovery"
failure mode that rejected Backdoor in §4. No re-partitioning needed.

**Corrected Table 1/2 — general metrics, frozen global model, genuinely
held-out test sets** (supersedes §11b's tables):

| Metric | UNSW-NB15 (82,332 rows) | ToN_IoT (31,656 rows) |
|---|---|---|
| Accuracy | 87.53% | 98.95% |
| Precision (Normal) | 86.23% | 97.39% |
| Precision (Attack) | 88.58% | 99.44% |
| Recall (Normal) | 85.98% | 98.19% |
| Recall (Attack) | 88.79% | 99.18% |
| Macro F1 | 0.8739 | 0.9855 |
| False Positive Rate | 14.02% | 1.81% |
| Fuzzers recall (official test, 6,062 rows) | 43.32% | — |

Payload size unchanged (14.27 KB — LoRA rank/params identical). Latency
re-measured 0.72ms median / 1.07ms p95 (comfortably under 50ms target,
consistent with before within measurement noise).

**Corrected Table 3 — federated Fuzzers recovery, 4 seeds (123/456/789/2024),
mean ± std, `cloud/multiround_fuzzers_experiment.py` now takes the seed as
a CLI arg** (`python -m cloud.multiround_fuzzers_experiment <seed>`) —
supersedes §11f/its seed-456 addendum entirely, those numbers are the
buggy backbone:

| Round | Cum. Fuzzers | Official-test recall | Replay-set acc | General acc | General FPR |
|---|---|---|---|---|---|
| 0 (before) | 0% | 43.32% | 29.79% | 87.53% | 14.02% |
| 4 (after, mean±std) | 100% | **63.37% ± 3.20pt** | **53.76% ± 3.57pt** | 85.37% ± 0.45pt | 23.91% ± 1.76pt |

Net: **+20.05pt ± 3.20pt** (official test), **+23.98pt ± 3.57pt** (replay
set) — this is the number to cite in the paper, with the ± std, since you
now actually have it across 4 independent seeds rather than resting on
one run. Per-seed round-4 values: official recall
[0.6176, 0.6744, 0.6008, 0.6420], replay acc
[0.5181, 0.5828, 0.5016, 0.5481] (seeds in the same order: 123/456/789/2024).

**Bonus finding from the fix**: the dramatic round-2 general-accuracy
collapse seen with the buggy backbone (§11f: 87.32%→63.89%→85.66%
recovery) **does not appear at all** with the fixed backbone across any
of the 4 seeds (round-to-round accuracy stays within ~1-2pt of round 1
throughout). Consistent with the theory that a real trained FFN gives
much better-conditioned representations than a permanently-random one,
making LoRA-only local updates far less prone to compounding drift. Worth
a sentence in the paper: fixing this bug incidentally also fixed an
instability that had been flagged as an open question.

**`model/validate_holdout.py` now reports an unusable, over-optimistic
number (100% after Device 1's solo retrain) — do NOT cite this script's
output.** It trains on an artificially clean, isolated Fuzzers-only slice
with zero benign examples mixed in (same known limitation flagged in
§11b for the pre-fix backbone) and evaluates a single un-federated
device — with the now-real FFN representations, this combination
overfits to a suspiciously perfect number, exactly the failure mode
§11e's discipline warns about. Table 3 above (the genuine multi-device
federated result) is the one that survived that scrutiny and is what
should be cited.

**Redeployed to all 4 EC2 nodes — done 2026-09-14** (same S3+SSM mechanism
as the original deploy, §11g): all 4 `fedgrid-agent` services stopped,
refreshed with the corrected `backbone_frozen.pt` (md5
`2758b9de9274ddeb477ef2dd8aade152`), restarted, confirmed `active`. The
live demo now matches every number in this section.

**Centralized non-federated baseline — built and run** (`model/
train_baseline_centralized.py`, doesn't deploy anywhere, exists only as a
reference point). Trains the SAME architecture, full parameters (no LoRA
restriction, same `unfreeze_ffn_base_for_pretraining()` fix applied), on
the raw union of `device{1..4}_train.csv` — Fuzzers included, since a
real non-privacy-preserving system has no reason to hide it. Evaluated on
the identical two held-out test sets as Table 1:

| Metric | Federated system (Table 1) | Centralized baseline |
|---|---|---|
| UNSW-NB15 accuracy | **87.53%** | 81.11% |
| UNSW-NB15 macro F1 | **0.8739** | 0.7964 |
| UNSW-NB15 FPR | **14.02%** | 39.66% |
| Fuzzers recall (UNSW) | 63.37% (after federated recovery) | **93.32%** (trained on it directly, no zero-day framing) |
| ToN_IoT accuracy | 98.95% | 98.98% (~tied) |
| ToN_IoT FPR | **1.81%** | 3.15% |

**Real, surprising, unresolved finding**: the federated system beats the
naive centralized baseline on general accuracy and FPR (both datasets),
despite the centralized model training on strictly more pooled raw data
with no privacy constraint. Checked and ruled out class-balance skew as
the explanation (pooled device union: 71.8% attack-labeled;
`central_pretrain_pool.csv`: 70.7% — nearly identical). Most likely
explanation, **not confirmed, worth investigating further before final
submission**: the raw non-IID Dirichlet-split device partitions carry
distributional quirks (feature co-occurrence patterns, not just label
balance) that the more curated `central_pretrain_pool.csv` doesn't. Don't
oversell this as "federation strictly improves accuracy" without digging
into why — but it's a legitimate, honestly-obtained result and a strong
paper finding either way: federation-with-LoRA here doesn't cost general
detection quality for the privacy benefit, only some zero-day recall
speed (which federated rounds recover progressively, per Table 3).

## 11. Decisions log

- 2026-08-23 — Locked: 4 EC2 instances as edge nodes (not laptops/Pi),
  SSM Session Manager only (no SSH), 2-dataset requirement (UNSW-NB15 +
  ToN_IoT/BoT-IoT), synchronous FedAvg via DynamoDB round-state, frozen
  backbone + LoRA-only federation, hold-out-attack-category demo design.
- 2026-08-23 (later same day) — EC2 provisioning + `sam deploy` explicitly
  deferred to start "tomorrow" per direct instruction; used the time
  instead to close the ToN_IoT independent-evaluation gap
  (`carve_test_split()`, §11b) rather than touch AWS. Also this session:
  attention-rollout explainability built (§11c), evaluation metrics
  built and run for real (§11b), local-training dilution bug found and
  fixed through two iterations (first fix caused catastrophic forgetting,
  caught by deliberately checking general performance, not assumed safe;
  second fix is the current authoritative one). Current authoritative
  demo number: Fuzzers hold-out replay 23.2%→73.9% (+50.7pt), DRI 0.66.

## 13. Demo-day incident and fixes (2026-09-21)

**The 4 EC2 edge nodes from §11g no longer existed.** Preparing for a
live mentor demo today, `describe_instances` on the 4 documented instance
IDs returned nothing, and `ap-south-1` had zero EC2 instances at all.
Confirmed via CloudTrail, not guessed: `TerminateInstances` was called on
all 4 (`i-0b21c5f1e75bcf14c`, `i-044fed5739b0e043e`, `i-0f7691cd6167f261d`,
`i-0d67c79d3e5805072`) on **2026-09-15 18:50 IST** by the `FEDGRID-DEPLOY`
identity — one day after this file's last entry, never recorded here.
Cause not identified (CloudTrail only attributes it to the shared deploy
identity, not a person) — worth asking the team before this happens again
silently. IAM role (`fedgrid-edge-node-role`), instance profile, security
group (`fedgrid-edge-node-sg`, `sg-09e0b27ace8f7b2a6`), and the S3 deploy
bundles/bootstrap script all survived, so re-provisioning was cheap.

**CORS was never configured on `FedGridApi`** — this is why the dashboard
showed "Failed to fetch" / fell back to DEMO DATA even though the API
itself worked fine (confirmed by curling it directly, real API keys,
real responses). No `Cors` property on the SAM API resource, and no
`Access-Control-Allow-Origin` header in any Lambda response — a browser
`fetch()` from `localhost:5174` was always going to be blocked, this was
never actually tested from a browser before today. **Fixed and deployed**:
`Cors` block added to `FedGridApi` in `template.yaml`, and
`Access-Control-Allow-Origin: *` added to `rounds_lambda`/
`incidents_read_lambda` responses (the two the dashboard calls). Verified
directly with a real cross-origin-style request post-deploy.

**`RETRAIN` decisions were never visible in the incident feed** — found
while checking why the dashboard's "training happened" story wouldn't
show up live. `agent.py`'s `RETRAIN` branch called the trainer + uploaded
the adapter, but never called `actuator.log_incident`, unlike BLOCK/ALERT.
The dashboard's `IncidentFeed.jsx` and `styles.css` (`badge-retrain`) had
already been built to render a RETRAIN row — mock data used it — but the
real code path never emitted one. **Fixed**: one line added
(`self.actuator.log_incident(self.device_id, decision)` in the RETRAIN
branch of `agent.py`'s `act()`). Not deployed to the cloud stack (this is
edge-side code) — baked into today's rebuilt device tarballs instead (see
below). `SYNC_DOWNLOAD` deliberately left unlogged — every device checks
this every ~15s, logging it would flood the feed with noise no one wants.

**Re-provisioned edge nodes, new instance IDs** (old ones above are now
invalid, don't reuse them):

| device | instance id | AZ |
|---|---|---|
| device-1 | `i-0b31d377eaacd6ca5` | ap-south-1a |
| device-2 | `i-02f3503e21b9f5efb` | ap-south-1c |
| device-3 | `i-02336b4f5de7011ac` | ap-south-1b |
| device-4 | `i-0ec77ce0efffbba45` | ap-south-1b (subnet `subnet-00a713decf1d60334`) |

Same AMI family (fetched the current latest AL2023 x86_64 AMI at
provisioning time rather than reusing the now-stale pinned one from §11g
— AMIs age out, the bootstrap installs everything itself so the exact AMI
build doesn't matter). Same IAM role/SG/no-key-pair setup as §5. All 4
confirmed SSM Online and `fedgrid-agent.service` `active (running)`
within ~5 minutes of launch, no `PendingVerification` hold this time.

**Per-device S3 deploy tarballs rebuilt and re-uploaded** with the
RETRAIN-logging fix baked in (`deploy/device{1..4}.tar.gz`), and
**`deploy/node_bootstrap.sh` updated** to arm `REPLAY_CSV`/`REPLAY_EVERY`
(`holdout_replay.csv`, every 10th row) automatically for devices 2-4 only
— needed because those devices have zero Fuzzers samples in their own
local partition by design (§4), so without replay injection they'd never
encounter the hold-out attack at all and the live before/after story
would have nothing to show. Device 1 is deliberately left without
`REPLAY_CSV` since it already sees Fuzzers natively.

**Verified working end-to-end post-redeploy**: `GET /incidents` returned
real BLOCK decisions from device4 within ~1 minute of the agents starting,
with real attention-rollout data attached, through the actual
EC2→API Gateway→Lambda→DynamoDB→dashboard path. `GET /rounds` still empty
at that point — expected, no federated round had completed yet.

**First CORS fix was incomplete — dashboard still showed "Failed to
fetch" after it.** `FedGridApi`'s API-level `Auth: ApiKeyRequired: true`
was applying to SAM's auto-generated CORS `OPTIONS` method too. A
browser's real preflight `OPTIONS` request never carries an API key (it
can't — preflights don't send custom headers), so API Gateway rejected
every preflight with `403 Forbidden` before the browser ever sent the
actual `GET`. This is invisible to `requests.get()`-style testing (what
was used to "verify" the first fix) because Python's `requests` never
performs a real preflight — only an actual browser does. Confirmed
directly by sending a real `OPTIONS` request with
`Access-Control-Request-Method`/`Access-Control-Request-Headers`, which
returned 403 with no CORS headers at all. **Fixed properly**: removed
`Auth: ApiKeyRequired: true` from `FedGridApi`'s top level, added it
instead to each individual method's own `Api` event (`Update`,
`GetModel`, `PostIncident`, `GetRounds`, `GetIncidents`) — the
auto-generated `OPTIONS` method isn't defined through an `Events` block,
so it's now correctly exempt from the key requirement by default.
Re-verified with a real preflight simulation post-deploy: `OPTIONS` now
returns 200 with proper `Access-Control-Allow-*` headers, real `GET`
still requires and accepts the API key. **Lesson for next time**: when
testing CORS, test the actual preflight (`OPTIONS` with
`Access-Control-Request-*` headers, no API key), not just the real
request with a scripted HTTP client — they exercise different code
paths in API Gateway.

**Cost/cleanup reminder**: these are new instances, billing from
2026-09-21. Stop (don't need to terminate) after today's demo — same
discipline as §5, and don't let today's termination mystery repeat
without at least a note here about who/what did it.

**Further live-demo findings, same session, after the CORS fix above:**

- **`LocalSelfEvalTrigger`'s "reliable" retrain trigger had silently never
  fired since the §12 backbone fix.** `accuracy_floor=0.85` was calibrated
  against the pre-§12 (buggy) backbone. After that fix, general accuracy
  rose enough that device1's own-buffer accuracy is 87.49% — ABOVE the old
  floor — so `should_retrain()` returned `False` every single time,
  forever, with the fixed backbone. Nobody caught this because every
  multiround experiment force-reveals Fuzzers tranches directly rather
  than waiting on this trigger; only running the real live EC2 demo for
  60+ real minutes (device1: 56 min / 73 steps, zero retrains) surfaced
  it. Measured device-by-device accuracy directly (not guessed): device1
  87.49%, device2 96.23%, device3 98.82%, device4 99.07%. **Fixed**:
  `accuracy_floor` raised to `0.90` (fires reliably on device1 only,
  matching original design intent).
- **Same function had a real performance bug**: `should_retrain()` did an
  unbatched per-row Python loop over the entire local buffer (104,606 rows
  for device1) on every check — ~46s/call in production, same class of
  bug already fixed once in `model/evaluate.py`'s `predict_all()` (§11b).
  Batched the same way, same fix pattern.
- **`MIN_STRAGGLER_PARTICIPANTS` lowered from 2 to 1** (`aggregate_lambda/
  handler.py`) after discovering that devices 2-4 have no organic path to
  ever retrain with the current, more-accurate backbone: their own-buffer
  accuracy (96-99%) is far above any reasonable self-eval floor, and
  `StreamDriftMonitor`'s confidence floor (0.6) is nowhere close to
  reachable even under aggressive hold-out replay injection (measured real
  average confidence ~0.91-0.95 even at 1-in-3 replay rate). Requiring
  ≥2 organic participants meant the round provably never completes, not
  just slowly. This is a genuine finding for the report, not a hack: this
  system's accuracy is high enough that only the device holding the
  rare/held-out class has any reason to update in a given round.
- **`MISS` incident type added** (`run_edge_node.py`'s traffic loop +
  `edge_agent/agent.py`'s `run_step()` now returns `(decision, pred_class,
  confidence)`) — a known hold-out-attack replay row that the agent's own
  decision didn't BLOCK/ALERT now gets explicitly logged as a visible
  `MISS` incident (dashboard: bold red badge, distinct from `BLOCK`). This
  closes a real gap: previously a "miss" was pure silence in the incident
  feed, giving the live demo no visible "before" evidence for the
  before/after story §8 describes. The agent itself never sees ground
  truth — this is demo-harness instrumentation (the harness controls the
  replay CSV and knows the true label), not something baked into the
  agent's decision logic.
- **`RETRAIN` decisions were never logged to the incident feed at all**
  (separate from the above) — `agent.py`'s RETRAIN branch called the
  trainer + uploaded the adapter but never called `actuator.log_incident`,
  unlike BLOCK/ALERT. Dashboard UI/CSS already supported a `RETRAIN` badge
  (mock data used it) but the real path never emitted one. Fixed: one line
  added.
- **`store.list_incidents()`/`list_rounds()` had a real correctness bug**:
  `table.scan(Limit=N)` caps how many items DynamoDB *evaluates* before
  returning, not how many survive a subsequent sort — sorting "the first N
  items Scan happened to touch" and calling it "most recent" is wrong
  whenever old and new data coexist in the table. Caught for real: the
  dashboard kept showing week-old incidents from the terminated Sept-14
  deployment as "current." A first fix (scan-all-then-sort, capped
  defensively at 5000 items) reproduced the identical bug one level down
  once the table grew past 24,000 items — DynamoDB Scan traverses in
  partition order, not timestamp order, so the cap kept the scan stuck
  inside one stale device's partition. Fixed properly: cap raised to a
  pure runaway-growth guard (100,000), not something a normal session
  hits. This in turn required bumping every Lambda's `Timeout` (15s→29s,
  API Gateway's hard ceiling) and `MemorySize` (256MB→1024MB, more
  CPU/network per invocation) since a genuine full-table scan of the
  (still mostly stale) 24K-item table was timing out. **Still a stopgap,
  not a real fix** — a real deployment needs a GSI on timestamp instead of
  scanning at all; a bulk delete of the stale pre-2026-09-21 items was
  attempted but blocked by the environment's safety classifier
  (mass-delete category) and never completed. The stale data is harmless
  now that sorting is correct, just wasteful.
- **Root cause of "only device4 showing" and "time looks wrong"**: two
  compounding effects — (1) the scan-before-sort bug above genuinely
  returning stale Sept-14/15 data, and (2) device4's local partition is
  genuinely 93.0% attack-labeled (measured: device1 56.2%, device2 84.3%,
  device3 49.2%, device4 93.0% — a real, expected outcome of the Dirichlet
  non-IID split, §4) so device4 legitimately fires BLOCK almost
  continuously once real data was actually being read.
- All 4 instances stopped (not terminated) via `ec2.stop_instances` at the
  end of the session, confirmed `stopped` state before moving on.

## 14. LoRA migration: hand-rolled → HuggingFace `peft` (2026-09-21)

**Why**: user-requested, explicitly to make the "hand-rolled LoRA/FedAvg"
story read as more standard/citable to a non-technical-enough reviewer.
Pushed back once on the premise (a hand-rolled implementation of a cited
paper's method is not less rigorous than importing a library, and FedAvg
staying hand-built is arguably the stronger systems claim) — overruled,
proceeded as directed. **Explicitly does NOT increase accuracy on its
own** — same LoRA math (Hu et al. 2021) whether hand-rolled or via `peft`,
verified directly (see below), not asserted.

**What changed**:
- `model/lora_adapter.py` (hand-rolled `LoRALinear`) is now dead code —
  nothing imports it. Deletion was attempted but blocked by the
  environment's safety classifier (irreversible-local-destruction
  category); still sitting in the repo, safe to `git rm` manually.
- `model/tabular_transformer.py`: `TabularTransformer` is now a PLAIN
  model (ordinary `nn.Linear` FFN, no LoRA at construction). New
  `wrap_with_lora(model, r=4, alpha=8)` applies `peft.LoraConfig`
  (`target_modules=["linear1","linear2"]`, `modules_to_save=["head"]`) via
  `peft.get_peft_model()` — called ONLY after central pretraining, on a
  device's own copy. This is a cleaner expression of the same
  LoRA-after-pretrain workflow than the old hand-rolled
  unfreeze/merge/freeze dance: the LoRA wrapper simply never exists during
  pretraining, so there's nothing to unfreeze or merge back in.
- Verified directly, in isolation, before touching production code (not
  assumed): `peft.get_peft_model()` on this exact custom
  `TransformerEncoder`-based architecture (a) forwards positional
  multi-arg calls (`model(x_cont, x_cat)`) correctly, (b) backprop +
  optimizer step work normally, (c) attribute access for anything peft
  doesn't define (`.cont_proj`, `.cat_embeds`, `.encoder`) transparently
  proxies to the wrapped base model — meaning `model/explain.py`'s
  `attention_rollout()` and `agent.py`'s `_explain()` needed **zero**
  changes despite directly poking at raw architecture internals.
- `peft_model.adapter_state_dict()` / `.load_adapter_state_dict()` /
  `.trainable_parameters()` are attached as bound methods (thin wrappers
  around `peft.get_peft_model_state_dict()` /
  `set_peft_model_state_dict()` / a `requires_grad` filter) so every
  existing call site (`edge_agent/trainer.py`, `edge_agent/inference.py`,
  `cloud/local_simulation.py`, `cloud/multiround_fuzzers_experiment.py`)
  kept working completely unchanged.
- `edge_agent/comms.py`'s `_flatten_state`/`_unflatten_state` simplified —
  peft's state dict is already a flat `{dotted_name: tensor}` dict (unlike
  the old 2-level nested one), so the flatten step is now just a
  tensor→numpy conversion, no more `rsplit`-based reconstruction needed.
- `cloud/shared/serialization.py`/`aggregate.py` needed **zero changes** —
  confirmed by reading them first: `weighted_average` is fully generic
  over an arbitrary flat `{name: array}` dict, never assumes a specific
  naming scheme.
- `model/train_backbone.py` / `train_baseline_centralized.py` simplified —
  no more `unfreeze_ffn_base_for_pretraining()` call needed (a plain model
  is already fully trainable).
- Real dependency conflict hit and left as-is (not yet resolved):
  installing `peft` pulled in `click==8.5.0`, conflicting with
  `aws-sam-cli`'s pin of `click==8.1.8`. `sam --version` still works
  despite the pip warning; watch for this if `sam build`/`deploy` starts
  failing later — may need a separate virtualenv for ML vs. deploy
  tooling.

**Backbone retrained** (same 10 epochs, same Fuzzers exclusion,
`central_pretrain_pool.csv`): 97.50% central validation accuracy (was
97.44% pre-migration, §12 — consistent with "no accuracy change expected,"
not evidence of an improvement).

**Corrected Table 1 — general metrics, frozen global model, genuinely
held-out test sets** (supersedes §12's table; same test files):

| Metric | UNSW-NB15 (82,332 rows) | ToN_IoT (31,656 rows) |
|---|---|---|
| Accuracy | 87.19% | 98.84% |
| Macro F1 | 0.8706 | 0.9840 |
| False Positive Rate | 14.31% | 1.93% |
| Fuzzers recall (official test, 6,062 rows) | 41.06% | — |

All within normal retrain-to-retrain variance of the §12 numbers
(87.53%/98.95%/14.02%/43.32%) — real difference, not a regression, most
likely from `train_backbone.py` never setting a random seed (see below).

**Real, disclosed regression**: inference latency roughly quadrupled —
mean 3.73ms / median 2.88ms / p95 6.65ms, vs. the hand-rolled version's
0.72ms median / 1.07ms p95 (§12). Still comfortably under the 50ms target,
but `peft`'s wrapper indirection genuinely costs more per forward pass
than the old direct computation — a real tradeoff of the library, not
noise. Payload size essentially unchanged (14.56 KB vs 14.27 KB).

**Corrected Table 3 — federated Fuzsers recovery, 4 seeds (123/456/789/
2024), mean ± std** (supersedes §12's Table 3 entirely — same seeds, same
`cloud/multiround_fuzzers_experiment.py`, only the underlying model
changed):

| Round | Cum. Fuzzers | Official-test recall | Replay-set acc | General acc | General FPR |
|---|---|---|---|---|---|
| 0 (before) | 0% | 41.06% | 28.14% | 87.19% | 14.31% |
| 4 (after, mean±std) | 100% | **49.13% ± 2.49pt** | **36.97% ± 3.07pt** | 86.55% ± 0.12pt | 17.71% ± 0.71pt |

Net: **+8.07pt ± 2.49pt** (official test), **+8.83pt ± 3.07pt** (replay
set). Per-seed round-4 values: official recall
[0.5025, 0.5210, 0.4741, 0.4677], replay acc
[0.3808, 0.4079, 0.3476, 0.3423] (seeds in order 123/456/789/2024).

**This is roughly HALF the §12 recovery** (+20.05pt ± 3.20pt official /
+23.98pt ± 3.57pt replay). Real, measured, disclosed — not spun. Verified
the peft-vs-hand-rolled LoRA math is mathematically equivalent (same
alpha/r scaling, same zero-init delta, same fully-trainable head
treatment) via the isolated test above, so this gap is NOT attributed to
the library swap. Most likely explanation, **not confirmed**:
`train_backbone.py` sets `random_state=42` for the train/val split but
never seeds `torch` itself — weight init and epoch-by-epoch batch
shuffling (`torch.randperm(n)`) are uncontrolled, so every retrain
produces a genuinely different backbone by chance, and the backbone's
starting representations plausibly matter more to how well one local LoRA
retrain can correct a specific blind spot than which library expresses
the LoRA math. **Fix `train_backbone.py` to call `torch.manual_seed(...)`
before training if this needs to be pinned down further** — not done yet,
flagging for whoever picks this up next, same discipline as every other
"found a real gap, disclosed it, didn't hide it" entry in this file.

**For the report**: cite Table 1/Table 3 above as current, cite §12's
numbers as the pre-migration reference point, and state the
migration-to-`peft` motivation honestly (readability/citability, not a
capability or accuracy improvement) — don't let "we migrated to a
standard library" imply "and therefore it got better," because the
measured data says the opposite on the one metric that matters most for
this project's headline story.

## 15. AWS-measured results, peft/Py3.9 fix, paper artifacts (2026-10-15)

- EC2 nodes run Python 3.9 -> peft 0.17.1 max (laptop 0.21.0). peft's
  get/set_peft_model_state_dict raised KeyError 'base_model.model.head.weight'
  on nodes. Fixed in model/tabular_transformer.py: adapter_state_dict /
  load_adapter_state_dict now copy trainable params by name (no peft funcs).
  Payload 15,026 B (14.67 KB).
- DynamoDB GLOBAL round state reset to round=13070, latest_global_round=0
  (stale old-format adapter in S3 global/round10892.json; nothing deleted).
- Experiments ran ON the 4 t3.small nodes (bundle deploy/experiments2.tar.gz,
  scripts deploy/run_experiments.sh, run_fed.sh). Cloud side was moto-mocked
  (same Lambda code), NOT the live API. seed 2024 OOMs when run in parallel
  on 2 GB nodes -> run alone.
- Frozen model: UNSW acc 87.19 / macroF1 .8706 / FPR 14.31 / Fuzzers recall
  41.06; ToN_IoT acc 98.84 / FPR 1.93. Latency ~1.7 ms median on t3.small.
- Federated Fuzzers, 4 seeds, round 4: recall 50.14+-2.59 (+9.08pt),
  acc 86.36+-0.17, FPR 18.26+-0.93. Centralized baseline (4 UNSEEDED runs):
  acc 83.5+-1.2, FPR 32.6+-3.5, Fuzzers recall 82.5+-4.8. Old 93% baseline
  recall = lucky draw, don't cite.
- Not met: synopsis >96% on UNSW; no adversarial eval; backbone unseeded;
  Muthuswamy/Vijetha citations unverified.
- Artifacts: paper_outline.md, literature_survey.md, paper_figures/ (fig1-7,
  make_figures.py, make_fig6.py).
- 4 EC2 instances left RUNNING (billing) -- stop when done.

## 16. Bug sweep, agent redesign, ablations (2026-10-15/16)

Bugs fixed (all verified with cloud/local_simulation.py):
- LocalTrainer val split took the first 15% of class-SORTED device CSVs ->
  val was 100% attack, whole classes never trained. Now shuffled (seed 0).
  Invalidated every federated number before this date; all rerun on EC2.
- Agent: self-eval re-scored ~100K rows on every benign flow + retrain storm
  (now 60 s / 300 s rate limits); drift window not cleared after retrain;
  SYNC starved under sustained attack (now independent of the flow).
- comms: any network error crashed the agent (now logged, returns None).
- aggregate: failed/empty aggregation left round stuck in "aggregating"
  forever (release_aggregation_lock); mismatched-key uploads dropped.
- ingest rejects n_samples<=0 / empty weights. Actuator refuses loopback/None.
- validate_holdout.py trained on Fuzzers only (all label 1) -> fake 100%.
- Lambdas redeployed 2026-10-15 with these fixes (backup zip in scratchpad).
Not fixed (paper limitations): FedAvg trusts client n_samples; late upload
during aggregation silently dropped; device data overlaps pretraining pool;
scaler stats include ToN test rows; CORS * + full scans on read endpoints.

New agent (edge_agent/policy.py, actuator.py, agent.py, triage.py):
cost-aware Bayes action choice (costs NOOP(0,10) ALERT(1,3) BLOCK(20,0));
graded blocks (TTL 60*2^(l-1), permanent at level 4); analyst rollback +
30-min exception + cost update; peer intel via GET /incidents with ROLLBACK
retraction; gated adoption of global models (acc -1pt / FPR +2pt tolerance);
LLM triage via Bedrock (off by default; account returns "Operation not
allowed" until Anthropic model access is enabled in console).
Experiments: cloud/ablation_experiment.py (ranks, full, mining, FGSM,
FedProx mu=.01, gate, poisoning, median), cloud/agent_policy_experiment.py.
Backbone v2 = per-feature tokens + 30 ep one-cycle (model/train_backbone.py
<seed> v2). Laptop dev: 88.57% / FPR 10.1% vs v1 87.19 / 14.31.
Poisoning finding: gate rejects 100% of poisoned globals but isolated device
drifts (FPR ~40%) -> added coordinate-median aggregation variant.
Ops gotchas: 2 GB nodes OOM with moto multiround -> 2 GB swap added;
scripts edited by Python on Windows get CRLF -> bash fails silently.
Results pipeline: paper_figures/build_results.py reads paper_figures/aws_logs.

## 17. Weak-point fixes (2026-10-16, EC2 exp10)
- Threshold-free eval added to ablation_experiment (AUROC, Fuzzers AUROC, Fuzzers recall @10% FPR). RESULT: federation does NOT improve separation (Fuzzers AUROC .823->.818; recall@10%FPR 38.0->34.8). Frozen backbone with threshold moved to the federated FPR gives the same recall (53.4 vs 54.5 at 19.2% FPR). Full-model federation degrades ranking (AUROC .950). Paper reframed: default-threshold recall overstates federated gains.
- model/gbm_reference.py (EC2, 3 seeds): 90.10+-0.17 acc, 8.92 FPR, Fuzzers 34.27. Centralized Transformer seeded (EC2, 3 seeds): 82.39 acc, 36.38 FPR, Fuzzers 89.76.
- model/operating_curve.py: frozen-model recall at given FPRs (RESULT_CURVE).
- Agent sim imperfect analyst (50% reviewed, 10/20% wrong) + exception TTL 30 vs 5 min: wrong rollbacks leak attacks (ToN 4.5% at 10% err); 5-min exception cuts ~2/3. A-E reproduce earlier numbers exactly.
- Normalisation leak quantified: <=0.058 sigma mean shift, <=2.4% std.
- Live backend: 12,610 rounds 2026-09-21..10-16, only 22 with all 4 devices.
- SSM stdout truncates at 24,000 chars: collect logs in chunks (scratchpad collect10.py).
