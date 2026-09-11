"""
model/tabular_transformer.py

Backbone: continuous features projected to d_model, categorical features
embedded, concatenated as a token sequence, passed through a small
self-attention encoder. Only the feed-forward projections inside each
encoder block (+ the classification head) are trainable after
`freeze_backbone()` -- everything else is frozen once central pretraining
finishes and is shipped identically to every edge device.

d_model/n_heads/n_layers below are placeholders sized for a small tabular
problem -- revisit once the real canonical feature count (from
data/scripts/partition_data.py) is known.
"""
import torch
import torch.nn as nn

from .lora_adapter import LoRALinear

# nn.TransformerEncoderLayer has a fused "fast path" that bypasses each
# submodule's forward() and reads linear1.weight/linear2.weight directly
# for a kernel call -- which would silently skip the LoRA delta entirely
# (not error, just quietly compute the wrong thing) once linear1/linear2
# are LoRALinear instead of plain nn.Linear. Must stay disabled.
torch.backends.mha.set_fastpath_enabled(False)


class TabularTransformer(nn.Module):
    def __init__(self, n_continuous, cat_cardinalities, d_model=32,
                 n_heads=4, n_layers=2, n_classes=2, lora_r=4, lora_alpha=8):
        super().__init__()
        self.cont_proj = nn.Linear(n_continuous, d_model)
        self.cat_embeds = nn.ModuleList(
            [nn.Embedding(card, d_model) for card in cat_cardinalities]
        )
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=n_heads, dim_feedforward=d_model * 4,
            batch_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        self._wrap_ffn_with_lora(lora_r, lora_alpha)
        self.head = nn.Linear(d_model, n_classes)

    def _wrap_ffn_with_lora(self, r, alpha):
        for layer in self.encoder.layers:
            layer.linear1 = LoRALinear(layer.linear1, r=r, alpha=alpha)
            layer.linear2 = LoRALinear(layer.linear2, r=r, alpha=alpha)

    def forward(self, x_cont, x_cat):
        tokens = [self.cont_proj(x_cont).unsqueeze(1)]
        for i, emb in enumerate(self.cat_embeds):
            tokens.append(emb(x_cat[:, i]).unsqueeze(1))
        seq = torch.cat(tokens, dim=1)  # (batch, n_tokens, d_model)
        encoded = self.encoder(seq)
        pooled = encoded.mean(dim=1)
        return self.head(pooled)

    def freeze_backbone(self):
        """Call once, right after central pretraining, before shipping the
        model to edge devices. Everything except the LoRA adapters and the
        head becomes non-trainable from this point on."""
        for p in self.parameters():
            p.requires_grad = False
        for p in self.trainable_parameters():
            p.requires_grad = True

    def trainable_parameters(self):
        for layer in self.encoder.layers:
            for module in (layer.linear1, layer.linear2):
                if isinstance(module, LoRALinear):
                    yield module.lora_A
                    yield module.lora_B
        yield from self.head.parameters()

    def adapter_state_dict(self):
        """What gets uploaded to the cloud and federated -- small, LoRA-only."""
        state = {"head": self.head.state_dict()}
        for i, layer in enumerate(self.encoder.layers):
            state[f"layer{i}.linear1"] = layer.linear1.adapter_state_dict()
            state[f"layer{i}.linear2"] = layer.linear2.adapter_state_dict()
        return state

    def load_adapter_state_dict(self, state):
        self.head.load_state_dict(state["head"])
        for i, layer in enumerate(self.encoder.layers):
            layer.linear1.load_adapter_state_dict(state[f"layer{i}.linear1"])
            layer.linear2.load_adapter_state_dict(state[f"layer{i}.linear2"])
