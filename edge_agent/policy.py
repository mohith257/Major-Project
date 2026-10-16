"""
edge_agent/policy.py

Decision rules the agent uses instead of hard-coded thresholds.

1. Cost-aware action choice (Bayes decision rule). For a flow with
   P(attack) = p, the expected cost of action a is
       E[cost | a] = (1 - p) * cost[a][benign] + p * cost[a][attack]
   and the agent takes argmin_a. The old rule ("BLOCK if p >= 0.9, else
   ALERT if p >= 0.5") is one fixed point of this; the cost table makes the
   trade-off explicit and tunable per deployment. The default costs are an
   ASSUMPTION (a false block = an outage for a legitimate host, weighted 20x
   an analyst glance) -- the paper reports sensitivity to them, not one
   "correct" table.

2. Analyst-feedback cost update. A BLOCK/ALERT the analyst marks as a false
   positive raises that action's benign-side cost (the agent becomes more
   conservative); a confirmed one lowers it slightly. Multiplicative, bounded.

3. Model-adoption gate. A device only adopts a candidate model (the global
   FedAvg average) if, on its own held-out local data, accuracy doesn't fall
   by more than tol_acc and FPR doesn't rise by more than tol_fpr. This is
   what lets an agent refuse a harmful or poisoned global update instead of
   loading whatever the cloud sends.
"""
import torch

# cost[action] = (cost if the flow is benign, cost if the flow is an attack)
DEFAULT_COSTS = {
    "NOOP": (0.0, 10.0),
    "ALERT": (1.0, 3.0),
    "BLOCK": (20.0, 0.0),
}


def expected_costs(p_attack, costs=DEFAULT_COSTS):
    return {a: (1 - p_attack) * c_benign + p_attack * c_attack
            for a, (c_benign, c_attack) in costs.items()}


def choose_action(p_attack, costs=DEFAULT_COSTS):
    exp = expected_costs(p_attack, costs)
    return min(exp, key=exp.get)


def threshold_action(p_attack, block_confidence=0.9):
    """The original rule, kept for comparison experiments."""
    if p_attack >= block_confidence:
        return "BLOCK"
    if p_attack >= 0.5:
        return "ALERT"
    return "NOOP"


def update_costs(costs, action, was_false_positive, lr=0.1, floor=0.1, cap=100.0):
    c_benign, c_attack = costs[action]
    c_benign = min(c_benign * (1 + lr), cap) if was_false_positive else max(c_benign * (1 - lr / 2), floor)
    return {**costs, action: (c_benign, c_attack)}


def acc_fpr(model, buffer, batch=4096):
    """Accuracy and false-positive rate of `model` on a list of
    (x_cont, x_cat, label) tuples."""
    if not buffer:
        return 0.0, 0.0
    x_cont = torch.stack([b[0] for b in buffer])
    x_cat = torch.stack([b[1] for b in buffer])
    y = torch.tensor([b[2] for b in buffer])
    model.eval()
    with torch.no_grad():
        pred = torch.cat([model(x_cont[i:i + batch], x_cat[i:i + batch]).argmax(-1)
                          for i in range(0, len(y), batch)])
    benign = y == 0
    fpr = (pred[benign] == 1).float().mean().item() if benign.any() else 0.0
    return (pred == y).float().mean().item(), fpr


def accept_update(before, after, tol_acc=0.01, tol_fpr=0.02):
    """before/after: (acc, fpr) on the same local held-out buffer."""
    return after[0] >= before[0] - tol_acc and after[1] <= before[1] + tol_fpr


def gated_load(model, candidate_state, val_buffer, tol_acc=0.01, tol_fpr=0.02):
    """Load candidate_state into model only if it passes accept_update on
    val_buffer; otherwise restore the previous adapter. Returns
    (accepted, before, after)."""
    previous = model.adapter_state_dict()
    before = acc_fpr(model, val_buffer)
    model.load_adapter_state_dict(candidate_state)
    after = acc_fpr(model, val_buffer)
    accepted = accept_update(before, after, tol_acc, tol_fpr)
    if not accepted:
        model.load_adapter_state_dict(previous)
    return accepted, before, after
