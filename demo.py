"""
demo.py

Offline jury demo, no AWS, no dashboard. Two parts:

  1. Attack catalogue: every attack type in UNSW-NB15 + ToN_IoT and how much
     of each the pretrained backbone catches. Fuzzers is the hold-out class
     (no device but device1 has it, and the backbone never saw it), so it
     shows up as the weak spot.
  2. Before/after on 2 devices: device1 has Fuzzers in its local data,
     device2 has never seen it. Both retrain locally, the adapters are
     FedAvg'd (the same weighted_average the ingest Lambda runs), and device2
     adopts the global model. Fuzzers detection + FPR on normal traffic, plus
     the agent's per-flow actions, are printed before and after.

FPR is printed next to every detection number on purpose: per the exp11
results, recall gained through federation comes with a higher FPR, and a jury
will ask about it.

Run: python demo.py
"""
import copy

import pandas as pd
import torch

from cloud.shared.serialization import weighted_average
from edge_agent.comms import _flatten_state, _unflatten_state
from edge_agent.inference import InferenceModel, SchemaEncoder
from edge_agent.policy import acc_fpr, choose_action
from edge_agent.trainer import LocalTrainer
from model.evaluate import _load_test_df, _load_ton_iot_test_df
from model.tabular_transformer import load_backbone, wrap_with_lora

torch.manual_seed(42)

ATTACK_INFO = {
    "fuzzers": "random/malformed input flood to crash a service",
    "generic": "attack against a block cipher, independent of its structure",
    "exploits": "exploits a known software vulnerability",
    "dos": "denial of service: exhausts a host's resources",
    "ddos": "distributed DoS from many sources",
    "reconnaissance": "probing/info gathering ahead of an attack",
    "scanning": "port/host scanning (nmap-style)",
    "analysis": "port scans, spam, HTML-file penetration",
    "backdoor": "bypasses auth to get covert remote access",
    "shellcode": "payload that spawns a shell on the victim",
    "worms": "self-replicating malware spreading across hosts",
    "injection": "SQL/command injection through user input",
    "xss": "cross-site scripting: injected browser scripts",
    "password": "brute-force / credential guessing",
    "ransomware": "encrypts victim data for ransom",
    "mitm": "man-in-the-middle: intercepts/alters traffic",
}

encoder = SchemaEncoder("data/processed/vocab.json", "data/processed/scaler.json")
backbone = load_backbone()


def p_attack(model, df, batch=4096):
    """P(attack) for every row of df, batched."""
    enc = [encoder.encode_row(r) for _, r in df.iterrows()]
    x_cont = torch.stack([e[0] for e in enc])
    x_cat = torch.stack([e[1] for e in enc])
    model.eval()
    with torch.no_grad():
        return torch.cat([model(x_cont[i:i + batch], x_cat[i:i + batch]).softmax(-1)[:, 1]
                          for i in range(0, len(df), batch)])


def encode_buffer(df):
    return [(*encoder.encode_row(r), int(r["label"])) for _, r in df.iterrows()]


# ---------------- PART 1: what attacks can a NIDS catch ----------------
print("=" * 78)
print("PART 1: attack types this NIDS detects (pretrained backbone, unseen test sets)")
print("=" * 78)
test = pd.concat([_load_test_df(), _load_ton_iot_test_df()], ignore_index=True)
test["cat"] = test["attack_cat"].str.lower()
test["p"] = p_attack(InferenceModel(wrap_with_lora(copy.deepcopy(backbone)), encoder).model, test).numpy()
normal = test[test["label"] == 0]
print(f"{'attack type':<16}{'flows':>8}{'detected':>10}  what it is")
for cat, g in sorted(test[test["label"] == 1].groupby("cat"), key=lambda kv: -(kv[1]["p"] > 0.5).mean()):
    print(f"{cat:<16}{len(g):>8}{(g['p'] > 0.5).mean():>9.1%}  {ATTACK_INFO.get(cat, '')}")
print(f"{'normal (FPR)':<16}{len(normal):>8}{(normal['p'] > 0.5).mean():>9.1%}  benign traffic wrongly flagged")
print("Fuzzers is the hold-out class: it was kept out of pretraining, so it is the blind spot.")

# ---------------- PART 2: before/after for 2 devices ----------------
print("\n" + "=" * 78)
print("PART 2: device1 has seen Fuzzers, device2 never has")
print("=" * 78)
fuzzers = pd.read_csv("data/processed/holdout_replay.csv")  # no device ever trains on these rows
normal_unsw = _load_test_df().query("label == 0")
sample = fuzzers.sample(n=8, random_state=7)

devices = {}
for did in ["device1", "device2"]:
    df = pd.read_csv(f"data/processed/{did}_train.csv")
    n_fuzz = (df["attack_cat"] == "Fuzzers").sum()
    model = InferenceModel(wrap_with_lora(copy.deepcopy(backbone)), encoder)
    devices[did] = {"model": model, "trainer": LocalTrainer(encode_buffer(df))}
    print(f"  {did}: {len(df)} local flows, {n_fuzz} of them Fuzzers")


def report(label):
    print(f"\n--- {label} ---")
    print(f"{'device':<10}{'Fuzzers caught':>16}{'FPR on normal':>16}")
    for did, d in devices.items():
        fz = (p_attack(d["model"].model, fuzzers) > 0.5).float().mean().item()
        fpr = (p_attack(d["model"].model, normal_unsw) > 0.5).float().mean().item()
        print(f"{did:<10}{fz:>15.1%}{fpr:>16.1%}")
    m2 = devices["device2"]["model"].model
    print(f"device2 agent actions on 8 Fuzzers flows:")
    for (_, row), p in zip(sample.iterrows(), p_attack(m2, sample).tolist()):
        print(f"    {row['src_ip']:<16} P(attack)={p:.2f}  -> {choose_action(p)}")


report("BEFORE: both devices on the pretrained backbone")

print("\nLocal retraining (raw data stays on each device)...")
updates = []
for did, d in devices.items():
    adapter = d["trainer"].local_retrain(d["model"])
    d["model"].load_adapter_state_dict(adapter)
    updates.append((_flatten_state(adapter), d["trainer"].last_batch_size))
    print(f"  {did}: local val acc {d['trainer'].last_val_accuracy:.4f}")
report("AFTER LOCAL TRAINING ONLY (no federation yet)")

print("\nFedAvg: only LoRA adapter weights are shared and averaged...")
global_adapter = _unflatten_state(weighted_average(updates))
d2 = devices["device2"]
before = acc_fpr(d2["model"].model, d2["trainer"].val_buffer)
for d in devices.values():
    d["model"].load_adapter_state_dict(global_adapter)
after = acc_fpr(d2["model"].model, d2["trainer"].val_buffer)
print(f"  device2 gate check on its own held-out data: acc {before[0]:.4f}->{after[0]:.4f}, "
      f"FPR {before[1]:.4f}->{after[1]:.4f}")
report("AFTER FEDERATION: device2 runs the global model")
