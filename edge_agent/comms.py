"""
edge_agent/comms.py

The only network boundary between an edge device and AWS. Everything that
crosses it is LoRA adapter weights + metadata (device id, sample count) --
never a raw flow record, never a raw dataset row. That's what makes the
"no raw data leaves the device" claim checkable, not just asserted.

Weights are sent as base64-encoded raw float arrays in a plain JSON body
(cloud/shared/serialization.py), NOT torch.save/pickle -- the Lambda side
never has PyTorch installed (see that module's docstring), so the wire
format has to be torch-free even though this side has full torch
available. This module is the only place that converts between the
peft-wrapped model's flat adapter state dict (torch tensors) and that
same-shaped flat wire format (numpy arrays, base64-encoded).
"""
import logging
import time

import numpy as np
import requests
import torch

from cloud.shared.serialization import decode_state, encode_state

logger = logging.getLogger("comms")


def _flatten_state(state: dict) -> dict:
    """model.adapter_state_dict() (peft.get_peft_model_state_dict() under
    the hood, since 2026-09-21) already returns a flat {dotted_name:
    tensor} dict -- just convert tensors to numpy for the wire format.
    Kept as its own function (rather than inlined) since upload_adapter/
    fetch_global_adapter call it symmetrically with _unflatten_state, and
    to keep this module's one job -- bridging torch tensors and the
    cloud's torch-free wire format -- explicit."""
    return {name: tensor.detach().cpu().numpy() for name, tensor in state.items()}


def _unflatten_state(flat: dict) -> dict:
    return {name: torch.from_numpy(np.asarray(arr).copy()) for name, arr in flat.items()}


def active_peer_blocks(incidents, device_id, since=float("-inf")):
    """IPs whose most recent BLOCK/ROLLBACK record from any OTHER device is a
    BLOCK. A ROLLBACK from any device (incl. this one) retracts the IP."""
    latest = {}
    for i in sorted(incidents, key=lambda i: i.get("timestamp", 0)):
        ip, act = i.get("source_ip"), i.get("action")
        if not ip or i.get("timestamp", 0) < since:
            continue
        if act == "ROLLBACK" or (act == "BLOCK" and i.get("device_id") != device_id):
            latest[ip] = act
    return {ip for ip, act in latest.items() if act == "BLOCK"}


class CloudComms:
    def __init__(self, api_base_url: str, api_key: str, device_id: str):
        self.api_base_url = api_base_url.rstrip("/")
        self.headers = {"x-api-key": api_key, "Content-Type": "application/json"}
        self.device_id = device_id
        self.last_known_round = 0

    # Every call below logs and returns None on a network/HTTP error instead of
    # raising: run_edge_node.py's loop only catches KeyboardInterrupt, so one
    # API Gateway timeout used to crash the agent (systemd restarts it, but
    # the local adapter + drift state were lost).
    def upload_adapter(self, device_id: str, adapter_state: dict, n_samples: int,
                        local_val_accuracy: float = 0.0):
        try:
            return self._upload(device_id, adapter_state, n_samples, local_val_accuracy)
        except requests.RequestException as e:
            logger.warning("upload failed, adapter kept locally: %s", e)
            return None

    def _upload(self, device_id, adapter_state, n_samples, local_val_accuracy):
        wire = encode_state(_flatten_state(adapter_state))
        resp = requests.post(
            f"{self.api_base_url}/update",
            headers=self.headers,
            json={
                "device_id": device_id, "n_samples": n_samples, "weights": wire,
                "local_val_accuracy": local_val_accuracy,
            },
            timeout=10,
        )
        resp.raise_for_status()
        body = resp.json()
        logger.info(
            "uploaded adapter: device=%s n_samples=%d round=%s aggregated=%s",
            device_id, n_samples, body.get("round"), body.get("aggregated"),
        )
        return body

    def fetch_global_adapter(self):
        try:
            return self._fetch()
        except requests.RequestException as e:
            logger.warning("global model fetch failed: %s", e)
            return None

    def _fetch(self):
        resp = requests.get(
            f"{self.api_base_url}/model",
            headers=self.headers,
            params={"since_round": self.last_known_round},
            timeout=10,
        )
        if resp.status_code == 204:
            return None  # no update since last poll
        resp.raise_for_status()
        body = resp.json()
        self.last_known_round = body["round"]
        return _unflatten_state(decode_state(body["weights"]))

    def fetch_peer_blocks(self, max_age_s=3600):
        """Shared threat intel: source IPs OTHER devices blocked recently,
        read from the same incidents table the dashboard uses (GET /incidents)
        -- no new endpoint, still only metadata (an IP + a verdict), never
        flow data."""
        try:
            resp = requests.get(f"{self.api_base_url}/incidents", headers=self.headers,
                                params={"limit": 200}, timeout=10)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.warning("peer-intel fetch failed: %s", e)
            return set()
        cutoff_ms = (time.time() - max_age_s) * 1000
        return active_peer_blocks(resp.json().get("incidents", []), self.device_id, cutoff_ms)

    def report_incident(self, entry: dict):
        try:
            requests.post(
                f"{self.api_base_url}/incidents", headers=self.headers, json=entry,
                timeout=10,
            ).raise_for_status()
        except requests.RequestException as e:
            logger.warning("incident report failed: %s", e)
