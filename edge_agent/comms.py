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
available. This module is the only place that converts between
TabularTransformer's nested tensor state dicts and that flat wire format.
"""
import logging

import numpy as np
import requests
import torch

from cloud.shared.serialization import decode_state, encode_state

logger = logging.getLogger("comms")


def _flatten_state(nested: dict) -> dict:
    """TabularTransformer.adapter_state_dict() returns a 2-level nested
    dict of tensors (outer key e.g. 'layer0.linear1', inner key e.g.
    'lora_A'). Flattened to dotted names + numpy arrays for the wire
    format. Uses rsplit on unflatten so an outer key that itself contains
    a dot (like 'layer0.linear1') doesn't get mis-split."""
    flat = {}
    for outer_key, inner in nested.items():
        for inner_key, tensor in inner.items():
            flat[f"{outer_key}.{inner_key}"] = tensor.detach().cpu().numpy()
    return flat


def _unflatten_state(flat: dict) -> dict:
    nested = {}
    for dotted_key, arr in flat.items():
        outer_key, inner_key = dotted_key.rsplit(".", 1)
        nested.setdefault(outer_key, {})[inner_key] = torch.from_numpy(
            np.asarray(arr).copy()
        )
    return nested


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
