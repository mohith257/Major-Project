"""
model/tabular_transformer.py

Backbone: continuous features projected to d_model, categorical features
embedded, concatenated as a token sequence, passed through a small
self-attention encoder. Only the feed-forward projections inside each
encoder block (+ the classification head) are trainable once
`wrap_with_lora()` is applied -- everything else is frozen once central
pretraining finishes and is shipped identically to every edge device.

d_model/n_heads/n_layers below are placeholders sized for a small tabular
problem -- revisit once the real canonical feature count (from
data/scripts/partition_data.py) is known.

LoRA (2026-09-21): this used to wrap linear1/linear2 with a hand-rolled
LoRALinear (model/lora_adapter.py, now unused/dead -- delete it) at
construction time, which meant central pretraining had to explicitly
unfreeze/re-freeze the FFN base and merge the trained delta back in
afterward (see git history / memory.md §12 for that whole saga). Replaced
with HuggingFace `peft`: the backbone is now a PLAIN model with ordinary
nn.Linear FFN layers, trained fully and normally, and `wrap_with_lora()`
is applied ONLY AFTER pretraining, to prepare a device's copy for local
fine-tuning. This is a cleaner expression of the same textbook
LoRA-after-pretrain workflow (Hu et al. 2021) -- adapt a real trained
weight starting from a genuinely zero delta -- with no separate merge step
needed, since the LoRA wrapper never exists during pretraining at all.
"""
import types

import torch
import torch.nn as nn
from peft import LoraConfig, get_peft_model, get_peft_model_state_dict, set_peft_model_state_dict

# nn.TransformerEncoderLayer has a fused "fast path" that bypasses each
# submodule's forward() and reads linear1.weight/linear2.weight directly
# for a kernel call. peft's LoRA-wrapped Linear (like the old hand-rolled
# LoRALinear before it) is not a plain nn.Linear and even exposes a
# `.weight` property for compatibility -- the fast path could still latch
# onto that and silently skip the LoRA delta entirely (wrong answer, not a
# crash). Must stay disabled for any peft-wrapped instance of this model.
torch.backends.mha.set_fastpath_enabled(False)


class TabularTransformer(nn.Module):
    def __init__(self, n_continuous, cat_cardinalities, d_model=32,
                 n_heads=4, n_layers=2, n_classes=2):
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
        self.head = nn.Linear(d_model, n_classes)

    def forward(self, x_cont, x_cat):
        tokens = [self.cont_proj(x_cont).unsqueeze(1)]
        for i, emb in enumerate(self.cat_embeds):
            tokens.append(emb(x_cat[:, i]).unsqueeze(1))
        seq = torch.cat(tokens, dim=1)  # (batch, n_tokens, d_model)
        encoded = self.encoder(seq)
        pooled = encoded.mean(dim=1)
        return self.head(pooled)


def wrap_with_lora(model: TabularTransformer, r: int = 4, alpha: int = 8):
    """Call once, on a plain (already centrally pretrained) TabularTransformer,
    to prepare it for local fine-tuning + federation. LoRA adapts the FFN
    linear layers inside each encoder block; the classification head is
    fully fine-tuned (peft's `modules_to_save`, not LoRA-adapted) -- same
    split of "what's actually federated" as the original hand-rolled
    design.

    Returns a `peft.PeftModel`. Attribute access for anything peft doesn't
    itself define (`.cont_proj`, `.cat_embeds`, `.encoder`, ...) proxies
    straight through to the wrapped TabularTransformer -- verified
    directly, not assumed -- so model/explain.py's attention_rollout()
    and everything else that pokes at the raw architecture needs no
    changes. Also attaches adapter_state_dict/load_adapter_state_dict/
    trainable_parameters as bound methods (thin wrappers around peft's own
    free functions) so every existing call site (edge_agent/trainer.py,
    edge_agent/inference.py, cloud/local_simulation.py, ...) keeps working
    completely unchanged against a peft-wrapped model, exactly as it did
    against the old hand-rolled LoRALinear."""
    config = LoraConfig(
        target_modules=["linear1", "linear2"], modules_to_save=["head"],
        r=r, lora_alpha=alpha,
    )
    peft_model = get_peft_model(model, config)
    peft_model.adapter_state_dict = types.MethodType(
        lambda self: get_peft_model_state_dict(self), peft_model)
    peft_model.load_adapter_state_dict = types.MethodType(
        lambda self, state: set_peft_model_state_dict(self, state), peft_model)
    peft_model.trainable_parameters = types.MethodType(
        lambda self: (p for p in self.parameters() if p.requires_grad), peft_model)
    return peft_model
