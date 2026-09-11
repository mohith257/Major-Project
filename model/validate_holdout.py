"""
model/validate_holdout.py

End-to-end proof of the demo's core premise (memory.md §8), run against
real data, not asserted: the frozen backbone genuinely cannot detect the
held-out "zero-day" class, and a single local LoRA retrain on Device 1's
own labeled data (the mechanism EdgeAgent.act() actually uses, not a
shortcut) fixes it. Run this once after model/train_backbone.py and
whenever the hold-out class or dataset split changes -- it's the fastest
way to catch a broken demo premise before touching AWS/EC2.
"""
import pandas as pd
import torch

from edge_agent.inference import InferenceModel, SchemaEncoder
from edge_agent.trainer import LocalTrainer
from model.tabular_transformer import TabularTransformer

CHECKPOINT_PATH = "model/backbone_frozen.pt"
VOCAB_PATH = "data/processed/vocab.json"
SCALER_PATH = "data/processed/scaler.json"
REPLAY_PATH = "data/processed/holdout_replay.csv"
DEVICE1_PATH = "data/processed/device1_train.csv"
HOLD_OUT_ATTACK_CATEGORY_UNSW = "Fuzzers"


def load_model():
    ckpt = torch.load(CHECKPOINT_PATH, weights_only=False)
    model = TabularTransformer(
        n_continuous=ckpt["n_continuous"], cat_cardinalities=ckpt["cat_cardinalities"]
    )
    model.load_state_dict(ckpt["model_state_dict"])
    return model


def evaluate_on_replay(inference_model, encoder, replay_df):
    correct = 0
    for _, row in replay_df.iterrows():
        logits = inference_model.infer(row)
        pred = logits.argmax(dim=-1).item()
        correct += int(pred == row["label"])
    return correct / len(replay_df)


def main():
    encoder = SchemaEncoder(VOCAB_PATH, SCALER_PATH)
    replay_df = pd.read_csv(REPLAY_PATH)

    model = load_model()
    inference_model = InferenceModel(model, encoder)

    before_acc = evaluate_on_replay(inference_model, encoder, replay_df)
    print(f"BEFORE any device 1 retrain: replay-set detection accuracy = {before_acc:.3f} "
          f"(this is what devices 2-4 would see live)")

    device1_df = pd.read_csv(DEVICE1_PATH)
    backdoor_rows = device1_df[device1_df["attack_cat"] == HOLD_OUT_ATTACK_CATEGORY_UNSW]
    local_buffer = [
        (*encoder.encode_row(row), int(row["label"])) for _, row in backdoor_rows.iterrows()
    ]

    trainer = LocalTrainer(local_buffer, epochs=5)
    new_adapter = trainer.local_retrain(inference_model)
    inference_model.load_adapter_state_dict(new_adapter)

    after_acc = evaluate_on_replay(inference_model, encoder, replay_df)
    print(f"AFTER device 1's local retrain (adapter uploaded, imagine FedAvg + "
          f"broadcast happened): replay-set detection accuracy = {after_acc:.3f}")
    print(f"delta: {after_acc - before_acc:+.3f}")


if __name__ == "__main__":
    main()
