"""
run_edge_node.py

Entrypoint that actually runs on each of the 4 EC2 edge nodes. Nothing else
in the repo wires EdgeAgent + its tools (model, trainer, drift monitors,
actuator, comms) into a running process -- every prior script
(cloud/local_simulation.py, cloud/multiround_fuzzers_experiment.py) drives
these pieces directly for testing, in-process, against moto-mocked AWS.
This is the one that talks to the REAL deployed API (see memory.md §11g).

All device-specific config comes from environment variables so the exact
same script runs unmodified on all 4 EC2 instances -- only the env vars
differ per instance (set once via SSM at deploy time). See memory.md §5/§6
for why each device gets its own API key and why the cloud never sees raw
flow data (only the LoRA adapter weights this script uploads via
CloudComms.upload_adapter cross the network boundary).

Traffic is CSV-replay of the device's own local partition, shuffled and
cycled indefinitely at ROW_RATE_HZ -- deterministic and safe for a live
demo, matching memory.md §8. Optional REPLAY_CSV/REPLAY_EVERY lets the demo
operator interleave holdout_replay.csv rows into devices 2-4's streams to
show the before/after hold-out-detection story live.

Env vars:
  DEVICE_ID        required, e.g. "device1"
  API_BASE_URL     required, e.g. https://xxx.execute-api.ap-south-1.amazonaws.com/demo
  API_KEY          required, this device's real API Gateway key value
  DATA_DIR         default "data/processed"
  ROW_RATE_HZ      default "2.0" -- local traffic replay rate
  SYNC_POLL_SECONDS default "15"
  BLOCK_CONFIDENCE  default "0.9" -- only used with POLICY=threshold
  POLICY            default "cost" -- "cost" = expected-cost action choice
                    (edge_agent/policy.py), "threshold" = original fixed rule,
                    "bandit" = learned LinUCB policy (edge_agent/bandit.py)
                    that also decides when to INVESTIGATE
  BANDIT_PRIOR      default "model/bandit_prior.npz" -- starting state if this
                    device has none yet (cloud/bandit_experiment.py --prior)
  BANDIT_STATE      default "model/bandit_<DEVICE_ID>.npz" -- loaded if present,
                    saved on exit; merge devices' files with
                    `python -m edge_agent.bandit merge OUT IN1 IN2 ...`
  BANDIT_ALPHA      default "0.5" -- LinUCB exploration bonus
  BANDIT_PRIOR_WEIGHT default "500" -- the prior is loaded as if learned from
                    this many flows, so live feedback can override it
  GATE_UPDATES      default "1" -- adopt a global model only if it doesn't
                    hurt this device's own held-out accuracy/FPR
  SHARE_INTEL       default "1" -- escalate faster on IPs peer devices blocked
  TRIAGE            default "0" -- "1" = LLM incident summaries via Bedrock
                    (edge_agent/triage.py), off the detection path; needs
                    bedrock:InvokeModel on the node role (not granted by default)
  TRIAGE_MODEL      default "global.anthropic.claude-haiku-5-5"
  INVESTIGATE       default "0" -- "1" = flows the cost policy would only
                    ALERT on are investigated by Claude with tools over this
                    device's per-source flow history (edge_agent/investigator.py)
                    before block/alert/allow/escalate; needs bedrock:InvokeModel
  INVESTIGATE_MODEL default "anthropic.claude-haiku-5-5" (Bedrock Mantle ID)
  BEDROCK_REGION    default "ap-south-1"
  REAL_BLOCK        default "0" -- "1" applies real iptables rules (Linux
                    only, see actuator.py); default stays simulate=True even
                    on Linux so a first run can't surprise-firewall the box.
  REPLAY_CSV        optional, e.g. data/processed/holdout_replay.csv
  REPLAY_EVERY      default "20" -- inject one REPLAY_CSV row every N normal rows
  LOG_LEVEL         default "INFO"
  LIVE_CAPTURE      default "0" -- "1" perceives REAL sniffed traffic
                    (edge_agent/live_capture.py) instead of CSV replay, so
                    an actual nmap/hping3/hydra run against this machine
                    drives the agent. Needs scapy installed + admin/root
                    (Npcap on Windows). REPLAY_CSV/REPLAY_EVERY are ignored
                    when this is on -- the live stream IS the traffic.
  CAPTURE_IFACE     optional, e.g. "Npcap Loopback Adapter" (Windows) or
                    "lo" (Linux); comma-separated for several, e.g.
                    "veth-h,ens5". Default: scapy's default interface.
  CAPTURE_FILTER    default "tcp or udp or icmp" -- a BPF filter. Narrow
                    this (e.g. exclude your API's host/port, or capture on
                    loopback only) so this process's own HTTPS calls to
                    the cloud API don't show up as "attack" flows.
  FLOW_TIMEOUT      default "2.0" -- seconds of silence before a live flow
                    is considered closed and scored.
  REPORT_CLEAR_EVERY default "5" -- in LIVE_CAPTURE mode, report 1-in-N
                    benign (NOOP) verdicts to the cloud so the dashboard
                    shows continuous live assessment, not just alerts.
                    BLOCK/ALERT/RETRAIN/MISS are always reported in full.
  FED_INTERVAL      default "120" -- seconds between scheduled federated
                    contributions (train on local data, upload adapter),
                    aligned to wall-clock boundaries so all nodes land in
                    the same round. "0" = upload only on RETRAIN (old).
  REPORT_MIN_INTERVAL default "10" -- at most one cloud incident per
                    (action, source_ip) per this many seconds. The local
                    log still gets every decision. Without it a scan posts
                    one incident per flow and trips the API's 10 rps limit.

Run: python run_edge_node.py
"""
import ipaddress
import logging
import os
import threading
import time

import pandas as pd

from edge_agent.actuator import DefenseActuator
from edge_agent.agent import EdgeAgent
from edge_agent.bandit import LinUCB
from edge_agent.comms import CloudComms
from edge_agent.drift_monitor import LocalSelfEvalTrigger, StreamDriftMonitor
from edge_agent.flow_history import FlowHistory
from edge_agent.inference import InferenceModel, SchemaEncoder
from edge_agent.trainer import LocalTrainer
from model.tabular_transformer import load_backbone, wrap_with_lora

logger = logging.getLogger("run_edge_node")


def load_config():
    device_id = os.environ["DEVICE_ID"]
    api_base_url = os.environ["API_BASE_URL"]
    api_key = os.environ["API_KEY"]
    data_dir = os.environ.get("DATA_DIR", "data/processed")
    ifaces = [i for i in os.environ.get("CAPTURE_IFACE", "").split(",") if i]
    return {
        "device_id": device_id,
        "api_base_url": api_base_url,
        "api_key": api_key,
        "data_dir": data_dir,
        "row_rate_hz": float(os.environ.get("ROW_RATE_HZ", "2.0")),
        "sync_poll_seconds": float(os.environ.get("SYNC_POLL_SECONDS", "15")),
        "block_confidence": float(os.environ.get("BLOCK_CONFIDENCE", "0.9")),
        "policy": os.environ.get("POLICY", "cost"),
        "gate_updates": os.environ.get("GATE_UPDATES", "1") == "1",
        "share_intel": os.environ.get("SHARE_INTEL", "1") == "1",
        "intel_scope_cidr": os.environ.get("INTEL_SCOPE_CIDR") or None,
        "triage": os.environ.get("TRIAGE", "0") == "1",
        "triage_model": os.environ.get("TRIAGE_MODEL", "global.anthropic.claude-haiku-5-5"),
        "investigate": os.environ.get("INVESTIGATE", "0") == "1",
        "investigate_model": os.environ.get("INVESTIGATE_MODEL", "anthropic.claude-haiku-5-5"),
        "bedrock_region": os.environ.get("BEDROCK_REGION", "ap-south-1"),
        "bandit_prior": os.environ.get("BANDIT_PRIOR", "model/bandit_prior.npz"),
        "bandit_state": os.environ.get("BANDIT_STATE", f"model/bandit_{device_id}.npz"),
        "bandit_alpha": float(os.environ.get("BANDIT_ALPHA", "0.5")),
        "bandit_prior_weight": int(os.environ.get("BANDIT_PRIOR_WEIGHT", "500")),
        "real_block": os.environ.get("REAL_BLOCK", "0") == "1",
        "replay_csv": os.environ.get("REPLAY_CSV"),
        "replay_every": int(os.environ.get("REPLAY_EVERY", "20")),
        "live_capture": os.environ.get("LIVE_CAPTURE", "0") == "1",
        # comma-separated = capture on several interfaces at once (e.g. the
        # netns sandbox AND the internet-facing NIC)
        "capture_iface": ifaces if len(ifaces) > 1 else (ifaces[0] if ifaces else None),
        "capture_filter": os.environ.get("CAPTURE_FILTER", "tcp or udp or icmp"),
        "flow_timeout": float(os.environ.get("FLOW_TIMEOUT", "2.0")),
        "report_clear_every": int(os.environ.get("REPORT_CLEAR_EVERY", "5")),
        "fed_interval": float(os.environ.get("FED_INTERVAL", "120")),
        "report_min_interval": float(os.environ.get("REPORT_MIN_INTERVAL", "10")),
    }


def rate_limited(send, min_interval):
    """Wrap an incident sink: drop repeats of the same (action, source_ip)
    inside min_interval seconds. Entries without a source IP (FL_UPLOAD,
    SYNC_DOWNLOAD, RETRAIN) always go through."""
    last = {}
    lock = threading.Lock()

    def sink(entry):
        ip = entry.get("source_ip")
        if ip and min_interval > 0:
            key, now = (entry.get("action"), ip), time.time()
            with lock:
                if now - last.get(key, 0) < min_interval:
                    return
                last[key] = now
        send(entry)
    return sink


def build_model(encoder: SchemaEncoder, backbone_path: str) -> InferenceModel:
    model = wrap_with_lora(load_backbone(backbone_path))
    return InferenceModel(model, encoder)


def encode_buffer(df: pd.DataFrame, encoder: SchemaEncoder):
    return [(*encoder.encode_row(row), int(row["label"])) for _, row in df.iterrows()]


def build_agent(cfg, encoder, model):
    local_df = pd.read_csv(f"{cfg['data_dir']}/{cfg['device_id']}_train.csv")
    local_buffer = encode_buffer(local_df, encoder)

    comms = CloudComms(cfg["api_base_url"], cfg["api_key"], cfg["device_id"])
    report = rate_limited(comms.report_incident, cfg["report_min_interval"])
    actuator = DefenseActuator(incident_sink=report, simulate=not cfg["real_block"])
    trainer = LocalTrainer(local_buffer)
    drift_monitor = StreamDriftMonitor()
    self_eval_trigger = LocalSelfEvalTrigger()

    # one per-source flow history, shared by the bandit (context features)
    # and the investigator (tool results)
    history = FlowHistory() if cfg["investigate"] or cfg["policy"] == "bandit" else None
    bandit = None
    if cfg["policy"] == "bandit":
        # Learned action policy (edge_agent/bandit.py), starting from the
        # federated prior (cloud/bandit_experiment.py --prior) or this
        # device's own saved state, and learning online from here.
        if os.path.exists(cfg["bandit_state"]):  # this device's own learned state
            path, bandit = cfg["bandit_state"], LinUCB.load(cfg["bandit_state"], alpha=cfg["bandit_alpha"])
        elif os.path.exists(cfg["bandit_prior"]):  # shared prior, discounted so live feedback can move it
            path, bandit = cfg["bandit_prior"], LinUCB.load(cfg["bandit_prior"], alpha=cfg["bandit_alpha"],
                                                            max_weight=cfg["bandit_prior_weight"])
        else:
            path, bandit = "(none: cold start, will learn slowly)", LinUCB(alpha=cfg["bandit_alpha"])
        logger.info("bandit policy: start state=%s (%d effective updates)", path, bandit.n_updates)

    agent = EdgeAgent(
        device_id=cfg["device_id"],
        model=model,
        drift_monitor=drift_monitor,
        self_eval_trigger=self_eval_trigger,
        trainer=trainer,
        actuator=actuator,
        comms=comms,
        block_confidence=cfg["block_confidence"],
        policy=cfg["policy"],
        gate_updates=cfg["gate_updates"],
        share_intel=cfg["share_intel"],
        sync_poll_interval=cfg["sync_poll_seconds"],
        history=history,
        bandit=bandit,
        intel_scope=ipaddress.ip_network(cfg["intel_scope_cidr"]) if cfg["intel_scope_cidr"] else None,
        fed_interval=cfg["fed_interval"],
    )
    if cfg["investigate"]:
        # Uncertain flows go to a Claude investigator that gathers per-source
        # evidence with tools before acting -- see edge_agent/investigator.py.
        # Needs bedrock:InvokeModel.
        from edge_agent.investigator import Investigator
        agent.investigator = Investigator(history, agent.threat_intel,
                                          region=cfg["bedrock_region"],
                                          model_id=cfg["investigate_model"])
    if cfg["triage"]:
        # LLM triage runs in a background thread AFTER the agent has already
        # acted -- see edge_agent/triage.py. Needs bedrock:InvokeModel.
        from edge_agent.triage import start_triage_worker
        submit = start_triage_worker(comms.report_incident, model_id=cfg["triage_model"])

        def sink(entry):
            report(entry)
            if entry["action"] in ("BLOCK", "ALERT"):
                submit(entry, agent.log[-5:])
        actuator.incident_sink = sink
    return agent, local_df, report


def traffic_stream(local_df: pd.DataFrame, replay_df, replay_every: int):
    """Infinite generator over the device's local partition, reshuffled
    every pass. If replay_df is given, every `replay_every`th row comes
    from it instead -- lets devices 2-4 demo the hold-out-attack pickup
    live (memory.md §8) without ever touching the training pipeline.
    Yields (row, is_replay) so the caller can tell a replay-injected row
    apart from the device's own traffic, for MISS-visibility logging."""
    step = 0
    while True:
        order = local_df.sample(frac=1.0).reset_index(drop=True)
        for _, row in order.iterrows():
            step += 1
            if replay_df is not None and step % replay_every == 0:
                yield replay_df.sample(n=1).iloc[0], True
            else:
                yield row, False


def main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config()
    logger.info("starting edge node device_id=%s api=%s real_block=%s live_capture=%s",
                cfg["device_id"], cfg["api_base_url"], cfg["real_block"], cfg["live_capture"])

    encoder = SchemaEncoder(f"{cfg['data_dir']}/vocab.json", f"{cfg['data_dir']}/scaler.json")
    model = build_model(encoder, "model/backbone_frozen.pt")
    agent, local_df, report = build_agent(cfg, encoder, model)

    def housekeeping():
        while True:
            try:
                agent.tick()
            except Exception:  # never let a sync/upload error kill the thread
                logger.exception("housekeeping tick failed")
            time.sleep(1.0)
    threading.Thread(target=housekeeping, daemon=True).start()
    logger.info("housekeeping thread up: sync every %ss, federated contribution every %ss",
                cfg["sync_poll_seconds"], cfg["fed_interval"] or "(RETRAIN only)")

    if cfg["live_capture"]:
        # Real sniffed traffic IS the stream -- no CSV replay, no pacing
        # sleep (packets already arrive at wall-clock speed). local_df
        # still backs trainer.local_buffer (labeled historical data for
        # RETRAIN's self-eval trigger) -- only the unlabeled perception
        # source changes, same split agent.py already assumes (see its
        # module docstring).
        from edge_agent.live_capture import sniff_flows
        logger.info(
            "LIVE CAPTURE armed: iface=%s filter=%r flow_timeout=%ss -- "
            "this machine's real traffic now drives the agent",
            cfg["capture_iface"] or "(default)", cfg["capture_filter"], cfg["flow_timeout"],
        )
        stream = ((flow, False) for flow in sniff_flows(
            iface=cfg["capture_iface"], flow_timeout=cfg["flow_timeout"],
            bpf_filter=cfg["capture_filter"],
        ))
        sleep_s = 0.0
    else:
        replay_df = pd.read_csv(cfg["replay_csv"]) if cfg["replay_csv"] else None
        if replay_df is not None:
            logger.info("demo replay armed: %s (%d rows), every %d-th step",
                         cfg["replay_csv"], len(replay_df), cfg["replay_every"])
        stream = traffic_stream(local_df, replay_df, cfg["replay_every"])
        sleep_s = 1.0 / cfg["row_rate_hz"]

    n_steps = 0
    clear_count = 0
    try:
        for row, is_replay in stream:
            decision, pred_class, confidence = agent.run_step(row)
            n_steps += 1
            if decision.action.name != "NOOP":
                logger.info("step=%d action=%s reason=%s conf=%s",
                            n_steps, decision.action.name, decision.reason,
                            decision.confidence)
            # Demo-visibility instrumentation, not agent logic (same split
            # as the MISS-logging below): in LIVE_CAPTURE mode, report a
            # sample of benign (NOOP) verdicts too -- without this the
            # dashboard only ever shows alerts, which looks identical to
            # "nothing is watching." BLOCK/ALERT/RETRAIN already report in
            # full via DefenseActuator's incident_sink.
            if cfg["live_capture"] and decision.action.name == "NOOP":
                clear_count += 1
                if clear_count % cfg["report_clear_every"] == 0:
                    report({
                        "device_id": cfg["device_id"],
                        "action": "NOOP",
                        "reason": "live flow classified benign",
                        "confidence": confidence,
                        "source_ip": getattr(row, "src_ip", None),
                    })
            # Demo-visibility instrumentation, not agent logic: the agent
            # itself never sees this row's ground-truth label, only the
            # harness does (it built the replay stream). A known hold-out
            # attack row that didn't get BLOCK/ALERT is a live "miss" --
            # log it explicitly so the before/after story (memory.md §8)
            # has a visible "before" instead of silence.
            if is_replay and int(row["label"]) == 1 and decision.action.name not in ("BLOCK", "ALERT"):
                logger.info("MISS: hold-out attack replayed, not caught (action=%s conf=%s)",
                            decision.action.name, confidence)
                report({
                    "device_id": cfg["device_id"],
                    "action": "MISS",
                    "reason": "hold-out attack replayed, model predicted benign",
                    "confidence": confidence,
                    "source_ip": getattr(row, "src_ip", None),
                })
            if sleep_s:
                time.sleep(sleep_s)
    except KeyboardInterrupt:
        logger.info("stopped after %d steps", n_steps)
    finally:
        if agent.bandit is not None:
            agent.bandit.save(cfg["bandit_state"])
            logger.info("bandit state saved to %s (%d updates)", cfg["bandit_state"], agent.bandit.n_updates)


if __name__ == "__main__":
    main()
