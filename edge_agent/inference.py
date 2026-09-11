"""
edge_agent/inference.py

Turns a canonical-schema row (a pandas Series from data/processed/
device{i}_train.csv, or an equivalent live-stream record with the same
fields) into the (x_cont, x_cat) tensors TabularTransformer.forward()
expects.

Loads vocab.json (categorical index lookup, __unk__ fallback) and
scaler.json (continuous feature normalization) once at startup -- both are
frozen, computed centrally during data partitioning (see
data/scripts/partition_data.py), and MUST be identical across all 4
devices: if each device built its own encoding independently, adapters
trained on different devices wouldn't even be averageable by FedAvg.
"""
import json
import math

import torch

from data.scripts.partition_data import (
    CANONICAL_CATEGORICAL,
    CANONICAL_CONTINUOUS,
    UNK_TOKEN,
)


class SchemaEncoder:
    def __init__(self, vocab_path, scaler_path):
        with open(vocab_path) as f:
            self.vocab = json.load(f)
        with open(scaler_path) as f:
            self.scaler = json.load(f)
        self._index = {
            col: {v: i for i, v in enumerate(values)}
            for col, values in self.vocab.items()
        }

    def cardinalities(self):
        """Ordered to match CANONICAL_CATEGORICAL -- pass straight into
        TabularTransformer(cat_cardinalities=...)."""
        return [len(self.vocab[c]) for c in CANONICAL_CATEGORICAL]

    def _encode_categorical(self, col, value):
        table = self._index[col]
        return table.get(str(value), table[UNK_TOKEN])

    def _encode_continuous(self, col, value):
        stats = self.scaler[col]
        log_val = math.log1p(max(float(value), 0.0))
        return (log_val - stats["mean"]) / stats["std"]

    def encode_row(self, row):
        """row: dict-like with the canonical column names as keys (a
        pandas Series works directly). Returns (x_cont, x_cat) as 1D
        tensors -- unsqueeze(0) for a single inference call, or
        torch.stack(...) across rows for a batch."""
        x_cont = torch.tensor(
            [self._encode_continuous(c, row[c]) for c in CANONICAL_CONTINUOUS],
            dtype=torch.float32,
        )
        x_cat = torch.tensor(
            [self._encode_categorical(c, row[c]) for c in CANONICAL_CATEGORICAL],
            dtype=torch.long,
        )
        return x_cont, x_cat


class InferenceModel:
    """Facade EdgeAgent actually holds as `self.model`. Adds the
    infer(flow_record) convenience perceive() calls, on top of a TabularTransformer
    -- and forwards every method agent.py / trainer.py / drift_monitor.py
    already call directly on `model` (trainable_parameters, __call__,
    train/eval, (load_)adapter_state_dict), so none of that code needed to
    change to accommodate this wrapper existing."""

    def __init__(self, model, encoder: SchemaEncoder, device="cpu"):
        self.model = model.to(device)
        self.encoder = encoder
        self.device = device

    def infer(self, flow_record):
        x_cont, x_cat = self.encoder.encode_row(flow_record)
        self.model.eval()
        with torch.no_grad():
            logits = self.model(
                x_cont.unsqueeze(0).to(self.device),
                x_cat.unsqueeze(0).to(self.device),
            )
        return logits.squeeze(0)

    def __call__(self, x_cont, x_cat):
        return self.model(x_cont, x_cat)

    def trainable_parameters(self):
        return self.model.trainable_parameters()

    def train(self):
        self.model.train()

    def eval(self):
        self.model.eval()

    def load_adapter_state_dict(self, state):
        self.model.load_adapter_state_dict(state)

    def adapter_state_dict(self):
        return self.model.adapter_state_dict()
