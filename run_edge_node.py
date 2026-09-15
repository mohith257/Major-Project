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
  BLOCK_CONFIDENCE  default "0.9"
  REAL_BLOCK        default "0" -- "1" applies real iptables rules (Linux
                    only, see actuator.py); default stays simulate=True even
                    on Linux so a first run can't surprise-firewall the box.
  REPLAY_CSV        optional, e.g. data/processed/holdout_replay.csv
  REPLAY_EVERY      default "20" -- inject one REPLAY_CSV row every N normal rows
  LOG_LEVEL         default "INFO"

Run: python run_edge_node.py
"""
import logging
import os
import time

import pandas as pd
import torch

from edge_agent.actuator import DefenseActuator
from edge_agent.agent import EdgeAgent
from edge_agent.comms import CloudComms
from edge_agent.drift_monitor import LocalSelfEvalTrigger, StreamDriftMonitor
from edge_agent.inference import InferenceModel, SchemaEncoder
from edge_agent.trainer import LocalTrainer
from model.tabular_transformer import TabularTransformer

logger = logging.getLogger("run_edge_node")


def load_config():
    device_id = os.environ["DEVICE_ID"]
    api_base_url = os.environ["API_BASE_URL"]
    api_key = os.environ["API_KEY"]
    data_dir = os.environ.get("DATA_DIR", "data/processed")
    return {
        "device_id": device_id,
        "api_base_url": api_base_url,
        "api_key": api_key,
        "data_dir": data_dir,
        "row_rate_hz": float(os.environ.get("ROW_RATE_HZ", "2.0")),
        "sync_poll_seconds": float(os.environ.get("SYNC_POLL_SECONDS", "15")),
        "block_confidence": float(os.environ.get("BLOCK_CONFIDENCE", "0.9")),
        "real_block": os.environ.get("REAL_BLOCK", "0") == "1",
        "replay_csv": os.environ.get("REPLAY_CSV"),
        "replay_every": int(os.environ.get("REPLAY_EVERY", "20")),
    }


def build_model(encoder: SchemaEncoder, backbone_path: str) -> InferenceModel:
    ckpt = torch.load(backbone_path, weights_only=False)
    model = TabularTransformer(
        n_continuous=ckpt["n_continuous"], cat_cardinalities=ckpt["cat_cardinalities"]
    )
    model.load_state_dict(ckpt["model_state_dict"])
    return InferenceModel(model, encoder)


def encode_buffer(df: pd.DataFrame, encoder: SchemaEncoder):
    return [(*encoder.encode_row(row), int(row["label"])) for _, row in df.iterrows()]


def build_agent(cfg, encoder, model):
    local_df = pd.read_csv(f"{cfg['data_dir']}/{cfg['device_id']}_train.csv")
    local_buffer = encode_buffer(local_df, encoder)

    comms = CloudComms(cfg["api_base_url"], cfg["api_key"], cfg["device_id"])
    actuator = DefenseActuator(
        incident_sink=comms.report_incident, simulate=not cfg["real_block"]
    )
    trainer = LocalTrainer(local_buffer)
    drift_monitor = StreamDriftMonitor()
    self_eval_trigger = LocalSelfEvalTrigger()

    agent = EdgeAgent(
        device_id=cfg["device_id"],
        model=model,
        drift_monitor=drift_monitor,
        self_eval_trigger=self_eval_trigger,
        trainer=trainer,
        actuator=actuator,
        comms=comms,
        block_confidence=cfg["block_confidence"],
        sync_poll_interval=cfg["sync_poll_seconds"],
    )
    return agent, local_df


def traffic_stream(local_df: pd.DataFrame, replay_df, replay_every: int):
    """Infinite generator over the device's local partition, reshuffled
    every pass. If replay_df is given, every `replay_every`th row comes
    from it instead -- lets devices 2-4 demo the hold-out-attack pickup
    live (memory.md §8) without ever touching the training pipeline."""
    step = 0
    while True:
        order = local_df.sample(frac=1.0).reset_index(drop=True)
        for _, row in order.iterrows():
            step += 1
            if replay_df is not None and step % replay_every == 0:
                yield replay_df.sample(n=1).iloc[0]
            else:
                yield row


def main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config()
    logger.info("starting edge node device_id=%s api=%s real_block=%s",
                cfg["device_id"], cfg["api_base_url"], cfg["real_block"])

    encoder = SchemaEncoder(f"{cfg['data_dir']}/vocab.json", f"{cfg['data_dir']}/scaler.json")
    model = build_model(encoder, "model/backbone_frozen.pt")
    agent, local_df = build_agent(cfg, encoder, model)

    replay_df = pd.read_csv(cfg["replay_csv"]) if cfg["replay_csv"] else None
    if replay_df is not None:
        logger.info("demo replay armed: %s (%d rows), every %d-th step",
                     cfg["replay_csv"], len(replay_df), cfg["replay_every"])

    sleep_s = 1.0 / cfg["row_rate_hz"]
    n_steps = 0
    try:
        for row in traffic_stream(local_df, replay_df, cfg["replay_every"]):
            decision = agent.run_step(row)
            n_steps += 1
            if decision.action.name != "NOOP":
                logger.info("step=%d action=%s reason=%s conf=%s",
                            n_steps, decision.action.name, decision.reason,
                            decision.confidence)
            time.sleep(sleep_s)
    except KeyboardInterrupt:
        logger.info("stopped after %d steps", n_steps)


if __name__ == "__main__":
    main()
