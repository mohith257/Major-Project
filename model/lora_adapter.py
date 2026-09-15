"""
model/lora_adapter.py

Wraps a frozen nn.Linear with a trainable low-rank update (Hu et al. 2021).
This is the ONLY thing that trains locally and gets federated -- the base
weight matrix is part of the shared, frozen backbone shipped identically to
every edge device.
"""
import torch
import torch.nn as nn


class LoRALinear(nn.Module):
    """
    Forward: y = W_0 x + b_0 + (alpha/r) * B(A x)
    W_0, b_0 are frozen. A, B are the only trainable parameters here.
    """

    def __init__(self, base_linear: nn.Linear, r: int = 4, alpha: int = 8):
        super().__init__()
        self.base = base_linear
        for p in self.base.parameters():
            p.requires_grad = False

        in_features = base_linear.in_features
        out_features = base_linear.out_features
        self.r = r
        self.scale = alpha / r
        self.lora_A = nn.Parameter(torch.randn(r, in_features) * 0.01)
        self.lora_B = nn.Parameter(torch.zeros(out_features, r))

    def forward(self, x):
        base_out = self.base(x)
        lora_out = (x @ self.lora_A.T) @ self.lora_B.T
        return base_out + self.scale * lora_out

    def adapter_state_dict(self):
        return {
            "lora_A": self.lora_A.detach().cpu(),
            "lora_B": self.lora_B.detach().cpu(),
        }

    def load_adapter_state_dict(self, state):
        with torch.no_grad():
            self.lora_A.copy_(state["lora_A"])
            self.lora_B.copy_(state["lora_B"])

    def merge_and_reset(self):
        """Fold the current LoRA delta into the frozen base, then reset the
        adapter to zero-effect (lora_B=0). Call once, right after the base
        was actually trained (jointly with A/B, during central
        pretraining) -- this is the textbook LoRA-after-pretrain workflow:
        adapt a real trained weight starting from zero delta, not a
        permanently-random base wearing a trained correction."""
        with torch.no_grad():
            self.base.weight += self.scale * (self.lora_B @ self.lora_A)
        nn.init.normal_(self.lora_A, std=0.01)
        nn.init.zeros_(self.lora_B)
