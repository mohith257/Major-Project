"""
cloud/shared/serialization.py

Wire format for adapter weights crossing the edge<->cloud boundary. Plain
numpy + base64 -- NOT torch.save/pickle. Lambda never has PyTorch
installed (a torch layer would blow past Lambda's package size limits for
no benefit, since the cloud side only ever averages numbers, it never runs
the model). Edge devices, which DO have torch, convert to/from this format
in edge_agent/comms.py.

Wire format for one adapter state:
{
  "<flat.dotted.name>": {"shape": [d0, d1, ...], "data_b64": "<base64 float32 bytes>"},
  ...
}
The nested torch state dicts TabularTransformer.adapter_state_dict()
produces are flattened to dotted names before this -- see
edge_agent/comms.py's _flatten_state / _unflatten_state.

No internal imports of other cloud.shared modules here, deliberately --
this file is imported both as `cloud.shared.serialization` (by edge-agent
code running from the repo root) and as `shared.serialization` (by Lambda
handlers running from the packaged cloud/ zip root), and having no
sibling-module imports means it works unmodified either way.
"""
import base64

import numpy as np


def encode_array(arr: np.ndarray) -> dict:
    arr = np.asarray(arr, dtype=np.float32)
    return {
        "shape": list(arr.shape),
        "data_b64": base64.b64encode(arr.tobytes()).decode("ascii"),
    }


def decode_array(entry: dict) -> np.ndarray:
    raw = base64.b64decode(entry["data_b64"])
    return np.frombuffer(raw, dtype=np.float32).reshape(entry["shape"])


def encode_state(flat_state: dict) -> dict:
    """flat_state: {name: array-like}"""
    return {name: encode_array(arr) for name, arr in flat_state.items()}


def decode_state(wire: dict) -> dict:
    """Returns {name: np.ndarray}"""
    return {name: decode_array(entry) for name, entry in wire.items()}


def coordinate_median(states_with_weights):
    """Byzantine-robust alternative to FedAvg (Yin et al. 2018): per-element
    median across clients, ignoring the self-reported n_samples (which an
    attacker controls). With K=4 one malicious client cannot move it far."""
    names = states_with_weights[0][0].keys()
    return {name: np.median(np.stack([s[name] for s, _ in states_with_weights]), axis=0).astype(np.float32)
            for name in names}


def weighted_average(states_with_weights):
    """states_with_weights: list of ({name: np.ndarray}, n_samples).
    Standard FedAvg: w_new = sum(n_i * w_i) / sum(n_i), per named tensor."""
    total_n = sum(n for _, n in states_with_weights)
    names = states_with_weights[0][0].keys()
    result = {}
    for name in names:
        acc = None
        for state, n in states_with_weights:
            contribution = state[name] * (n / total_n)
            acc = contribution if acc is None else acc + contribution
        result[name] = acc
    return result
