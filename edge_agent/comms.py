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


class CloudComms:
    def __init__(self, api_base_url: str, api_key: str, device_id: str):
        self.api_base_url = api_base_url.rstrip("/")
        self.headers = {"x-api-key": api_key, "Content-Type": "application/json"}
        self.device_id = device_id
        self.last_known_round = 0

    def upload_adapter(self, device_id: str, adapter_state: dict, n_samples: int,
                        local_val_accuracy: float = 0.0):
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

    def report_incident(self, entry: dict):
        requests.post(
            f"{self.api_base_url}/incidents", headers=self.headers, json=entry,
            timeout=10,
        )
