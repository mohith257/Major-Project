# Agentic FedGrid — Live Demo Runbook (viva / jury)

**Opening line:** *"Four edge nodes on AWS, each on the public internet. Each one detects intrusions with a
transformer classifier, firewalls the attacker on its own, trains on its own private data, and shares only model
weights and attacker IPs. No raw traffic leaves a node."*

**Ground rules:**
- The dashboard is **read-only**. You never click anything to make something happen.
- Attacks come from a **separate physical machine**: your laptop, or better, a juror's phone or laptop.
- Evidence is **raw**: the agent log and `iptables -S`, not banners.

**Targets.** Every node watches its public interface and accepts peer intel for any IP. Attack any one node, and the
attacker is blocked on all four within ~15s.

| Node | Public IP | Policy |
|---|---|---|
| device-1 | 35.154.172.128 | threshold (+ netns sandbox, `fg-scan`) |
| device-2 | 3.109.0.101 | threshold (+ netns sandbox) |
| device-3 | 65.1.112.185 | learned bandit |
| device-4 | 13.235.241.61 | cost-aware |

---

## 0. Before the room (10 min early, then DO NOT TOUCH)

- Dashboard: `cd dashboard && npm run dev`, then open it. Check:
  - **Nodes live 4/4**.
  - **FL round** closed under 2 min ago.
  - Topology shows **no grey nodes**.
- Open SSM sessions (Console → Systems Manager → Session Manager):
  - **device-2** tab A (agent log):
    `sudo tail -f /var/log/fedgrid-agent.log | grep --line-buffered -E "BLOCK|ALERT|FL_UPLOAD|GLOBAL"`
  - **device-2** tab B (firewall): `sudo iptables -S INPUT | tail`
  - **device-3** tab C (firewall): `sudo iptables -S INPUT | tail`
- Have the attacker machine ready (`attack.ps1` / `attack.sh`).
- **Each source IP is single-use per hour.** Once one node blocks it, peer intel makes the other nodes block it too,
  and `fg-arm` no longer clears it (device-2 re-learns the block from its peers on restart). For a second run,
  switch networks (phone hotspot), or wait 1 hour.

---

## ACT 1 — "It's federated, live, right now" (~90s) — dashboard only

| Point at | What they see | You say |
|---|---|---|
| Topology + KPI | 4/4 nodes live, round N, "4/4 nodes in last round" | "Four independent nodes. Every 2 minutes each one trains on its own private data and uploads only adapter weights." |
| Live Event Stream | `FL_UPLOAD` rows from device1..4: "trained on 88916 private local rows… sent to round N" | "Those are the four contributions to this round." |
| Wait ≤2 min | round counter **increments**; `SYNC_DOWNLOAD` / `REJECT_GLOBAL` rows | "The averaged model came back. Each node tested it on its own held-out data before adopting it. That one was **rejected** because its false-positive rate went up. The node refuses a global model that's worse for it." |

`REJECT_GLOBAL` is your strongest agentic-and-federated moment. Read its numbers out loud.

---

## ACT 2 — "Attack it from a real machine" (~90s)

| Where | Action | What appears | You say |
|---|---|---|---|
| Tab B | `sudo iptables -S INPUT \| grep <attacker-ip>` | nothing | "Attacker isn't blocked yet." |
| Attacker machine | `powershell -ExecutionPolicy Bypass -File .\attack.ps1` (or a juror's phone port-scanner app → `3.109.0.101`) | SYNs across 18 ports | "Port-scanning device-2 across the internet." |
| Tab A | (watch) | `BLOCK source_ip <attacker-ip> conf 0.9x` + attention | "Detected and decided on its own, with the features that drove it." |
| Tab B | re-run the grep | `-A INPUT -s <attacker-ip> -j DROP` | "That's the kernel rule it wrote." |
| Dashboard | device-2 red, attacker IP shown | | |
| Attacker machine | open/curl `http://3.109.0.101:8080` | **times out** | "And now the attacker can't reach anything on this node." |

Background internet scanners get blocked during the demo too. Point them out when they show up, because that's real-world traffic.

---

## ACT 3 — "One node is attacked, all nodes are protected" (~60s) — federated threat intel

| Where | What appears (≤15s after Act 2) | You say |
|---|---|---|
| Dashboard | device-3 and device-4 turn **amber** with the same attacker IP; KPI "Pre-blocked via peer intel" goes up | "device-3 and device-4 were never touched by this attacker." |
| Tab C (device-3) | `sudo iptables -S INPUT \| grep <attacker-ip>` → DROP | "But they've already firewalled it, because device-2 shared the verdict through the cloud. Just an IP and a verdict, no traffic." |
| Attacker machine | curl `http://65.1.112.185:8080` (device-3) | **times out** | "The attacker is locked out of nodes it never touched." |

---

## ACT 3.5 — "Every attack class, live through the model" (~60s) — optional, high-impact

The live wire sensor only sees SYNs, so it can't *show* a ransomware flow vs a DoS flow.
To show class breadth honestly, replay **real held-out attack flows** (ToN-IoT test set +
the Fuzzers hold-out — flows no node trained on) through the **same model + policy** a node runs:

```
python demo_attack_feed.py                 # terminal scoreboard, every class interleaved
python demo_attack_feed.py --report --api-base <API_BASE_URL> --api-key <key>   # also stream to the dashboard (device_id "replay-demo")
```

You see `[BLOCK] ddos … P(attack)=1.00`, `[BLOCK] ransomware …`, `[MISS ] fuzzers …` scroll by,
with a per-class caught/total tally. **Say it straight:** *"These are real held-out attack flows
replayed into the live agent — not live wire, not fabricated. The model is a binary detector; it
outputs P(attack). The attack name is the dataset's ground-truth label. Fuzzers is the one it
misses — that's our negative result."* With `--report`, these show under `replay-demo`, not as a
real node, and they do inflate the "sources blocked" KPI — point that out rather than hide it.

Canonical per-class numbers (`python demo.py`, unseen UNSW-NB15 + ToN-IoT, P(attack)>0.5):

| Class | Detected | | Class | Detected |
|---|---|---|---|---|
| scanning | 100.0% | | ddos | 98.8% |
| password | 99.9% | | reconnaissance | 97.8% |
| analysis | 99.7% | | mitm | 95.5% |
| xss | 99.7% | | dos | 94.6% |
| backdoor | 99.6% | | exploits | 91.5% |
| injection | 99.6% | | worms | 79.5% |
| ransomware | 99.2% | | shellcode | 53.2% |
| generic | 98.9% | | **fuzzers (hold-out)** | **41.1%** |

Benign false-positive rate on this combined set: **12.2%**. Fuzzers was kept out of pretraining —
that's why it's the blind spot, and why `demo.py` PART 2 shows federation lifting device-2's
Fuzzers recall (28% → 39% global, with FPR dropping 14.9% → 7.8% through the gate).

---

## ACT 4 — "What it actually detects" (~60s)

Per-dataset benchmark table (`python -m model.evaluate_per_attack`, run beforehand):

**ToN-IoT** (benign false-positive rate **1.9%**)

| Attack type | Detected |
|---|---|
| Scanning | 100% |
| Password / backdoor | 99.9% |
| Ransomware | 99.2% |
| DDoS | 98.8% |
| DoS | 95.8% |
| MITM | 95.5% |

**UNSW-NB15** (benign false-positive rate **14.3%**)

| Attack type | Detected |
|---|---|
| Analysis | 99.7% |
| Generic | 98.9% |
| Backdoor | 98.5% |
| Recon | 97.8% |
| DoS | 93.7% |
| Exploits | 91.5% |
| Shellcode (weak) | 53% |
| Fuzzers (weak) | 41% |

Say the weak classes out loud. "Federation didn't fix Fuzzers either. That's a negative result in the paper."

---

## The honest-scope sentences (a sharp examiner WILL ask)

1. *"The live demo proves the detect → decide → firewall → share pipeline on real infrastructure. The accuracy
   numbers come from held-out benchmarks. The live sensor only sees inbound connection attempts (SYNs), so its features
   are coarse. That's why many live verdicts carry the same confidence. We keep the two claims separate on purpose."*
2. *"The live nodes run a threshold/cost policy for a deterministic demo. The learned bandit policy runs on device-3.
   The Claude-based investigator for uncertain flows is in the code and paper but switched off live."*

---

## If something breaks

| Symptom | Fix |
|---|---|
| A node grey on the topology | `systemctl status fedgrid-agent` on it via SSM. The dashboard only shows nodes that report, so grey means really down. |
| Round counter not moving for >4 min | check `uploaded adapter` lines in a node's log. The straggler closes a round 180s after it opens. |
| No BLOCK after the scan | your IP is probably already blocked from an earlier run (see the single-use rule). Switch network. |
| Dashboard "BACKEND UNREACHABLE" | demo from the SSM tabs. They're the primary evidence anyway. |

## After the viva — mandatory
- Delete the `0.0.0.0/0` rule on `sg-09e0b27ace8f7b2a6`.
- Stop the instances.
- Rotate the API keys. They were exposed via the public `/tmp` http.server.
