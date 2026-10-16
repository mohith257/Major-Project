"""
model/explain.py

Attention-rollout explainability (Objective 5; Abnar & Zuidema 2020,
"Quantifying Attention Flow in Transformers"). This is the piece your
synopsis promised against Panwar & Abdelrahman's black-box critique and
that had nothing implemented at all until now.

Deliberately NOT hooked into TabularTransformer.forward() -- PyTorch's
TransformerEncoderLayer calls self_attn internally with need_weights=False
by default (a fast-path optimization, same category of gotcha already
documented in tabular_transformer.py for the LoRA wrapping). Rather than
fight that internal call site, this recomputes attention explicitly by
calling each layer's self_attn submodule directly with need_weights=True,
then runs the layer's real forward() to advance the sequence correctly for
the next layer's rollout step.

Each sample is 4 tokens (continuous features, proto, service, state -- see
edge_agent/inference.py's SchemaEncoder), no CLS token. "Importance" per
token is read as total attention RECEIVED across the rollout (column
sums, normalized to sum to 1) -- a heuristic attribution, not a causal
explanation. Say that plainly wherever this is surfaced (dashboard,
report), don't oversell it as a proof of causation.
"""
import torch

from data.scripts.partition_data import CANONICAL_CONTINUOUS

TOKEN_NAMES = ["continuous_features", "proto", "service", "state"]


def _build_tokens(model, x_cont, x_cat):
    return model.tokens(x_cont, x_cat)  # (batch, n_tokens, d_model)


def token_names(model):
    if model.per_feature_tokens:
        return list(CANONICAL_CONTINUOUS) + TOKEN_NAMES[1:]
    return TOKEN_NAMES


def attention_rollout(model, x_cont, x_cat):
    """model: the raw TabularTransformer (not the InferenceModel facade).
    x_cont, x_cat: single-sample tensors, shape (1, ...) -- unsqueeze(0)
    before calling if you have a bare row. Returns
    {token_name: importance_fraction}, fractions sum to 1."""
    model.eval()
    with torch.no_grad():
        seq = _build_tokens(model, x_cont, x_cat)  # (1, 4, d_model)

        rollout = None
        for layer in model.encoder.layers:
            _, attn_weights = layer.self_attn(
                seq, seq, seq, need_weights=True, average_attn_weights=True,
            )  # (1, 4, 4), averaged over heads
            a = attn_weights[0]  # (4, 4)
            # account for the residual connection (Abnar & Zuidema eq. 1)
            a_hat = 0.5 * a + 0.5 * torch.eye(a.shape[0])
            a_hat = a_hat / a_hat.sum(dim=-1, keepdim=True)
            rollout = a_hat if rollout is None else a_hat @ rollout
            # advance seq through the layer's REAL forward (attention +
            # LoRA-adapted FFN + residual + norm) so the next layer's
            # rollout step operates on the actual post-layer representation
            seq = layer(seq)

        importance = rollout.sum(dim=0)  # total attention received per token
        importance = importance / importance.sum()

    return {name: float(importance[i]) for i, name in enumerate(token_names(model))}
