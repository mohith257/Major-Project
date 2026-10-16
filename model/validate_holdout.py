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
from model.evaluate import _load_test_df, classification_metrics, predict_all
from model.tabular_transformer import load_backbone, wrap_with_lora

CHECKPOINT_PATH = "model/backbone_frozen.pt"
VOCAB_PATH = "data/processed/vocab.json"
SCALER_PATH = "data/processed/scaler.json"
REPLAY_PATH = "data/processed/holdout_replay.csv"
DEVICE1_PATH = "data/processed/device1_train.csv"


def load_model():
    return wrap_with_lora(load_backbone(CHECKPOINT_PATH))


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

    # Device 1's FULL mixed local buffer, as EdgeAgent actually retrains on.
    # An earlier version trained on the Fuzzers rows alone -- every label was
    # 1, so the model learned "everything is an attack" and this script
    # printed a meaningless 100%. Report test FPR too so a collapse is visible.
    device1_df = pd.read_csv(DEVICE1_PATH)
    local_buffer = [
        (*encoder.encode_row(row), int(row["label"])) for _, row in device1_df.iterrows()
    ]
    test_df = _load_test_df()
    before = classification_metrics(*predict_all(inference_model, test_df))

    trainer = LocalTrainer(local_buffer, epochs=5)
    new_adapter = trainer.local_retrain(inference_model)
    inference_model.load_adapter_state_dict(new_adapter)

    after_acc = evaluate_on_replay(inference_model, encoder, replay_df)
    print(f"AFTER device 1's local retrain (adapter uploaded, imagine FedAvg + "
          f"broadcast happened): replay-set detection accuracy = {after_acc:.3f}")
    print(f"delta: {after_acc - before_acc:+.3f}")
    after = classification_metrics(*predict_all(inference_model, test_df))
    print(f"official test: acc {before['accuracy']:.4f} -> {after['accuracy']:.4f}, "
          f"FPR {before['false_positive_rate']:.4f} -> {after['false_positive_rate']:.4f}")


if __name__ == "__main__":
    main()
