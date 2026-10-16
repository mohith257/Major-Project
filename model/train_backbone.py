"""
model/train_backbone.py

Central, one-time, offline pretraining of the shared backbone. Run this
locally (CPU is fine -- the model is tiny and the pool is ~280K rows,
finishes in well under a minute; a GPU/Colab buys nothing here and just
adds a checkpoint-export step). Not something that runs on the EC2 edge
nodes or in the cloud -- this happens once, before any device exists, and
the resulting checkpoint is what gets shipped identically to all 4.

Trains on data/processed/central_pretrain_pool.csv, which
data/scripts/partition_data.py builds specifically to exclude the hold-out
"zero-day" attack class (UNSW's Backdoor + ToN_IoT's independent backdoor
type) under any name, from either dataset. That exclusion is what makes
the demo -- "devices 2-4 can't detect it until FedAvg propagates device
1's local training" -- genuinely true rather than scripted. See memory.md
§4/§7/§8.

This trains a PLAIN model (peft LoRA wrapping happens separately, only
once this checkpoint gets loaded onto a device for local fine-tuning --
see model/tabular_transformer.py's wrap_with_lora()). Every parameter here
trains normally; there's no LoRA wrapper to unfreeze or merge back in
during central pretraining anymore.
"""
import pandas as pd
import torch
import torch.nn as nn
from sklearn.model_selection import train_test_split

from data.scripts.partition_data import CANONICAL_CONTINUOUS
from edge_agent.inference import SchemaEncoder
from model.tabular_transformer import TabularTransformer

DATA_PATH = "data/processed/central_pretrain_pool.csv"
VOCAB_PATH = "data/processed/vocab.json"
SCALER_PATH = "data/processed/scaler.json"
CHECKPOINT_PATH = "model/backbone_frozen.pt"


def load_dataset(encoder: SchemaEncoder):
    df = pd.read_csv(DATA_PATH)
    conts, cats = [], []
    for _, row in df.iterrows():
        x_cont, x_cat = encoder.encode_row(row)
        conts.append(x_cont)
        cats.append(x_cat)
    x_cont = torch.stack(conts)
    x_cat = torch.stack(cats)
    labels = torch.tensor(df["label"].values, dtype=torch.long)
    return x_cont, x_cat, labels


def train(epochs=10, lr=1e-3, batch_size=256, device="cpu", seed=0,
          per_feature_tokens=False, one_cycle=False, out_path=CHECKPOINT_PATH):
    # Seeded and best-on-validation (was: unseeded, last epoch kept), so the
    # backbone behind every reported number can be regenerated exactly.
    torch.manual_seed(seed)
    encoder = SchemaEncoder(VOCAB_PATH, SCALER_PATH)
    x_cont, x_cat, labels = load_dataset(encoder)

    x_cont_tr, x_cont_val, x_cat_tr, x_cat_val, y_tr, y_val = train_test_split(
        x_cont, x_cat, labels, test_size=0.15, stratify=labels, random_state=42
    )

    arch = {"per_feature_tokens": True} if per_feature_tokens else {}
    model = TabularTransformer(
        n_continuous=len(CANONICAL_CONTINUOUS),
        cat_cardinalities=encoder.cardinalities(), **arch,
    ).to(device)

    opt = torch.optim.Adam(model.parameters(), lr=lr)
    sched = (torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=2 * lr, total_steps=epochs * ((len(y_tr) + batch_size - 1) // batch_size))
        if one_cycle else None)
    loss_fn = nn.CrossEntropyLoss()
    best_acc, best_state = -1.0, None

    n = len(y_tr)
    for epoch in range(epochs):
        model.train()
        perm = torch.randperm(n)
        total_loss = 0.0
        for i in range(0, n, batch_size):
            idx = perm[i : i + batch_size]
            opt.zero_grad()
            logits = model(x_cont_tr[idx].to(device), x_cat_tr[idx].to(device))
            loss = loss_fn(logits, y_tr[idx].to(device))
            loss.backward()
            opt.step()
            if sched:
                sched.step()
            total_loss += loss.item() * len(idx)

        model.eval()
        with torch.no_grad():
            val_logits = model(x_cont_val.to(device), x_cat_val.to(device))
            val_acc = (val_logits.argmax(dim=-1).cpu() == y_val).float().mean().item()
        print(
            f"epoch {epoch + 1}/{epochs}  "
            f"train_loss={total_loss / n:.4f}  val_acc={val_acc:.4f}"
        )
        if val_acc > best_acc:
            best_acc, best_state = val_acc, {k: v.clone() for k, v in model.state_dict().items()}

    model.load_state_dict(best_state)
    torch.save(
        {
            "model_state_dict": best_state,
            "n_continuous": len(CANONICAL_CONTINUOUS),
            "cat_cardinalities": encoder.cardinalities(),
            "arch": arch,
            "seed": seed,
            "best_val_acc": best_acc,
        },
        out_path,
    )
    print(f"saved frozen backbone -> {out_path} (best val_acc={best_acc:.4f})")
    return model


if __name__ == "__main__":
    import sys
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    if len(sys.argv) > 2 and sys.argv[2] == "v2":
        # v2: one token per continuous feature + 30 epochs one-cycle schedule
        train(epochs=30, seed=seed, per_feature_tokens=True, one_cycle=True)
    else:
        train(seed=seed)
