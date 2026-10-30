"""
edge_agent/bandit.py

The learning part of the agent: a LinUCB contextual bandit (Li et al. 2010)
that picks NOOP / ALERT / BLOCK / INVESTIGATE for each flow, replacing the
hand-set cost rule and its fixed "uncertain band".

  context  the classifier's P(attack) + the source's recent behaviour from
           FlowHistory (connection-state mix, host/service fan-out, how its
           earlier flows scored) + whether a peer device blocked it
  action   one of ACTIONS; INVESTIGATE hands the source to the Claude
           investigator, which costs money/latency but returns a verdict
  reward   -(cost of the action given the true label) / 20, using the same
           cost table as policy.py, plus INVESTIGATE_COST per LLM call

Why a bandit and not deep RL: an IDS action barely changes which flows come
next, so this is (close to) a one-step decision -- the bandit setting --
not a long-horizon MDP.

Federation is exact here, unlike FedAvg on network weights: each arm's
state is a sum of per-flow terms (A = lam*I + sum x x^T, b = sum r x), so
summing devices' statistics gives exactly the bandit that one device would
have learned from all of their feedback. merge() does that.

Ports are deliberately NOT a feature: the offline ToN_IoT data has none, so
a bandit trained on it could not use them live. The investigator still sees
ports through its tools.
"""
import math
import sys
from collections import Counter

import numpy as np

from edge_agent.policy import DEFAULT_COSTS

ACTIONS = ["NOOP", "ALERT", "BLOCK", "INVESTIGATE"]
INVESTIGATE_COST = 0.5  # per LLM call, in the same units as DEFAULT_COSTS
FEATURES = ["bias", "p_attack", "logit_p", "log_prev_flows", "frac_reset", "frac_incomplete",
            "log_dst_hosts", "log_services", "median_prev_p", "frac_prev_p_gt_half", "peer_flagged"]


def context(history, ip, p_attack, now, peer_flagged=False):
    """Feature vector for one flow. Uses only the source's flows BEFORE this
    one, so call it before history.add() for the current flow."""
    prev = history.window(ip, now) if ip else []
    n = len(prev)
    lp = math.log(max(p_attack, 1e-4) / max(1 - p_attack, 1e-4))
    x = [1.0, p_attack, max(-1.0, min(1.0, lp / 5)), math.log1p(n) / 5]
    if n:
        states = Counter(f["state"] for f in prev)
        ps = sorted(f["p_attack"] for f in prev)
        x += [states["rejected_reset"] / n, states["incomplete_other"] / n,
              math.log1p(len({f["dst_ip"] for f in prev})) / 5,
              math.log1p(len({f["service"] for f in prev})) / 3,
              ps[n // 2], sum(p > 0.5 for p in ps) / n]
    else:
        x += [0.0] * 6
    x.append(1.0 if peer_flagged else 0.0)
    return np.array(x)


def action_cost(action, is_attack, verdict_attack=None):
    """Cost of one decision. INVESTIGATE: the LLM call plus the cost of what
    the investigator's verdict then does (BLOCK if it says attack, else NOOP)."""
    if action == "INVESTIGATE":
        follow = "BLOCK" if verdict_attack else "NOOP"
        return INVESTIGATE_COST + DEFAULT_COSTS[follow][int(is_attack)]
    return DEFAULT_COSTS[action][int(is_attack)]


class LinUCB:
    def __init__(self, d=len(FEATURES), actions=ACTIONS, alpha=1.0, lam=1.0):
        self.actions, self.alpha, self.lam = list(actions), alpha, lam
        self.A = np.stack([lam * np.eye(d) for _ in self.actions])
        self.b = np.zeros((len(self.actions), d))
        self.n_updates = 0
        self.rng = np.random.default_rng(0)

    def scores(self, x, alpha=None):
        alpha = self.alpha if alpha is None else alpha
        out = []
        for A, b in zip(self.A, self.b):
            A_inv_x = np.linalg.solve(A, x)
            out.append(A_inv_x @ b + alpha * math.sqrt(max(x @ A_inv_x, 0.0)))
        return np.array(out)

    def choose(self, x, allowed=None, alpha=None):
        s = self.scores(x, alpha)
        if allowed is not None:
            s = np.where([a in allowed for a in self.actions], s, -np.inf)
        # random tie-break: an untrained bandit scores every arm equally, and
        # argmax would then always pick NOOP -- which live never earns a label,
        # so it would never learn. Live runs should still start from a prior.
        best = np.flatnonzero(s >= s.max() - 1e-12)
        return self.actions[int(self.rng.choice(best))]

    def update(self, x, action, reward):
        i = self.actions.index(action)
        self.A[i] += np.outer(x, x)
        self.b[i] += reward * x
        self.n_updates += 1

    def save(self, path):
        np.savez(path, A=self.A, b=self.b, lam=self.lam, n_updates=self.n_updates,
                 actions=np.array(self.actions))

    @classmethod
    def load(cls, path, alpha=1.0, max_weight=None):
        """max_weight: if set, shrink the loaded evidence to at most that many
        effective updates. A prior learned from ~180K offline flows would
        otherwise be so confident that live feedback could never move it --
        and offline data doesn't cover live traffic (it extrapolates badly)."""
        z = np.load(path)
        bandit = cls(d=z["A"].shape[1], actions=[str(a) for a in z["actions"]],
                     alpha=alpha, lam=float(z["lam"]))
        bandit.A, bandit.b, bandit.n_updates = z["A"], z["b"], int(z["n_updates"])
        if max_weight is not None and bandit.n_updates > max_weight:
            w = max_weight / bandit.n_updates
            prior = bandit.lam * np.eye(bandit.A.shape[1])
            bandit.A = prior + w * (bandit.A - prior)
            bandit.b = w * bandit.b
            bandit.n_updates = max_weight
        return bandit


def merge(bandits):
    """Federated aggregation: sum every device's sufficient statistics, keeping
    one copy of the lam*I prior. Exact -- equals centralised training."""
    out = LinUCB(d=bandits[0].A.shape[1], actions=bandits[0].actions,
                 alpha=bandits[0].alpha, lam=bandits[0].lam)
    prior = out.A.copy()
    out.A = prior + sum(bd.A - prior for bd in bandits)
    out.b = sum(bd.b for bd in bandits)
    out.n_updates = sum(bd.n_updates for bd in bandits)
    return out


if __name__ == "__main__":
    # python -m edge_agent.bandit merge OUT.npz IN1.npz IN2.npz ...
    if len(sys.argv) < 4 or sys.argv[1] != "merge":
        sys.exit("usage: python -m edge_agent.bandit merge OUT.npz IN1.npz IN2.npz ...")
    merged = merge([LinUCB.load(p) for p in sys.argv[3:]])
    merged.save(sys.argv[2])
    print(f"merged {len(sys.argv) - 3} bandits, {merged.n_updates} updates -> {sys.argv[2]}")
