import sys, numpy as np, pandas as pd, torch
sys.path.insert(0, ".")
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from edge_agent.inference import SchemaEncoder
from model.tabular_transformer import load_backbone
from model.explain import attention_rollout, TOKEN_NAMES

torch.manual_seed(0)
enc = SchemaEncoder("data/processed/vocab.json", "data/processed/scaler.json")
m = load_backbone(); m.eval()
from model.evaluate import _load_test_df
df = _load_test_df()
res = {}
for lab, name in [(0, "normal"), (1, "attack")]:
    sub = df[df["label"] == lab].sample(300, random_state=0)
    acc = np.zeros(4)
    for _, r in sub.iterrows():
        xc, xk = enc.encode_row(r)
        xc = torch.as_tensor(xc, dtype=torch.float32).unsqueeze(0); xk = torch.as_tensor(xk, dtype=torch.long).unsqueeze(0)
        d = attention_rollout(m, xc, xk); acc += [d[t] for t in TOKEN_NAMES]
    res[name] = acc / len(sub)
x = np.arange(4); w = .35
plt.figure(figsize=(6, 3.5))
plt.bar(x - w/2, res["normal"], w, label="normal flows"); plt.bar(x + w/2, res["attack"], w, label="attack flows")
plt.xticks(x, ["continuous\nfeatures", "proto", "service", "state"]); plt.ylabel("mean rollout importance")
plt.title("Attention rollout (n=300/class, UNSW-NB15 raw test)"); plt.legend(); plt.tight_layout()
plt.savefig("paper_figures/fig6_attention_rollout.png", dpi=200)
print({k: v.round(3).tolist() for k, v in res.items()})
