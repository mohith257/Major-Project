"""
edge_agent/trainer.py

Local fine-tuning: only LoRA adapter params (+ head) get gradients, per
TabularTransformer.freeze_backbone(). That's what keeps a single local
retrain fast enough to run inside a live demo.

Contrastive adversarial training (Objective 4): each step trains on both
the clean batch and an FGSM-perturbed version of it, so the local model
doesn't just fit the clean distribution.

Mini-batched with ONLINE HARD-EXAMPLE-WEIGHTED SAMPLING, not a single
full-batch step over the whole local buffer. This exists because of a
real, measured problem, not a hypothetical one: Device 1's actual local
buffer is ~88% traffic the model already handles fine (Normal/Generic/
Exploits) and ~12% the newly-relevant pattern (Fuzzers, in the hold-out
demo). A single full-batch gradient step over the whole mixed buffer
diluted the signal so badly the demo's headline improvement dropped from
+15.2 points (an isolated, single-class training slice) to +5.7 points
(the realistic mixed buffer) -- measured, not assumed, see memory.md §4/§8.

The fix: before each epoch, weight every example by the model's CURRENT
loss on it (classic online hard-example mining) and sample minibatches
proportionally. Examples the model already handles confidently contribute
almost nothing; examples it's failing on dominate the sampling. This needs
no attack-category label at all -- only the binary label real
analyst-reviewed local data would realistically carry -- so it concentrates
learning on Fuzzers without the trainer ever being told "this is Fuzzers."

FIRST VERSION OF THIS FIX CAUSED CATASTROPHIC FORGETTING, measured, not
hypothetical: `steps_per_epoch = n // batch_size` scaled with buffer size,
so a 104K-row buffer produced ~1,634 steps/epoch x 5 epochs = ~8,170 total
gradient steps -- not a lightweight LoRA nudge, a full retraining run.
Combined with unbounded loss-based sampling weights, it collapsed general
test accuracy from 86.9% to 50.3% and blew false-positive rate up from
12% to 65.4%, while "fixing" Fuzzers detection to 86.7% -- a model that
flags two-thirds of legitimate traffic as malicious is not a working
IDS. See memory.md §11b for the full before/after.

Fixed properly: `steps_per_epoch` is now a FIXED constant, independent of
buffer size -- that's what keeps a local retrain an actual lightweight
nudge no matter how large a device's local buffer is. Sampling weights
are clipped and floored (`max_loss_weight`, `weight_floor`) so the ratio
between the hardest and easiest example stays bounded -- majority-class
signal never disappears from training entirely, it's just outweighed, not
eliminated.

Also holds out a small validation slice of the local buffer (not trained
on) to self-report `last_val_accuracy` after each retrain -- see
memory.md §6 for how this feeds the dashboard's accuracy chart. Report it
as "federated validation accuracy", not "test accuracy" -- see the note
there for why.
"""
import torch
import torch.nn as nn
import torch.nn.functional as F


class LocalTrainer:
    def __init__(self, local_buffer, device="cpu", epochs=5, lr=1e-3,
                 adversarial_epsilon=0.05, val_fraction=0.15, batch_size=64,
                 steps_per_epoch=20, max_loss_weight=3.0, weight_floor=0.3):
        # local_buffer: list of (x_cont, x_cat, label) -- this device's own
        # analyst-labeled historical data, NOT the live unlabeled stream.
        n_val = max(1, int(len(local_buffer) * val_fraction)) if local_buffer else 0
        self.val_buffer = local_buffer[:n_val]
        self.local_buffer = local_buffer[n_val:] or local_buffer  # don't train on nothing
        self.device = device
        self.epochs = epochs
        self.lr = lr
        self.adversarial_epsilon = adversarial_epsilon
        self.batch_size = batch_size
        # FIXED, independent of buffer size -- epochs * steps_per_epoch is
        # the entire local-retrain step budget regardless of whether the
        # device has 100 or 100,000 local rows. See module docstring for
        # why this matters (it's the actual fix for measured catastrophic
        # forgetting, not a hypothetical concern).
        self.steps_per_epoch = steps_per_epoch
        self.max_loss_weight = max_loss_weight
        self.weight_floor = weight_floor
        self.last_batch_size = 0
        self.last_val_accuracy = 0.0

    def _fgsm_perturb(self, model, x_cont, x_cat, label, loss_fn):
        x_cont = x_cont.clone().detach().requires_grad_(True)
        logits = model(x_cont, x_cat)
        loss = loss_fn(logits, label)
        grad = torch.autograd.grad(loss, x_cont)[0]
        return (x_cont + self.adversarial_epsilon * grad.sign()).detach()

    def _hard_example_weights(self, model, x_cont, x_cat, labels):
        """Per-example sampling weight = current model's loss on it,
        CLIPPED then floored so the ratio between the hardest and easiest
        example stays bounded (default: at most 11x -- (3.0+0.3)/0.3).
        Recomputed every epoch: as the model improves on what was hard,
        sampling shifts to whatever's hard next. The clip+floor is what an
        earlier, unbounded version of this was missing -- see module
        docstring for the measured catastrophic-forgetting result that
        caused."""
        model.eval()
        with torch.no_grad():
            logits = model(x_cont, x_cat)
            per_example_loss = F.cross_entropy(logits, labels, reduction="none")
        return per_example_loss.clamp(max=self.max_loss_weight) + self.weight_floor

    def local_retrain(self, model):
        loss_fn = nn.CrossEntropyLoss()
        opt = torch.optim.Adam(model.trainable_parameters(), lr=self.lr)
        x_cont, x_cat, labels = self._batch()
        self.last_batch_size = len(labels)

        for _ in range(self.epochs):
            weights = self._hard_example_weights(model, x_cont, x_cat, labels)
            idx_pool = torch.multinomial(
                weights, self.steps_per_epoch * self.batch_size, replacement=True
            )

            model.train()
            for step in range(self.steps_per_epoch):
                idx = idx_pool[step * self.batch_size:(step + 1) * self.batch_size]
                opt.zero_grad()
                clean_logits = model(x_cont[idx], x_cat[idx])
                clean_loss = loss_fn(clean_logits, labels[idx])

                adv_x_cont = self._fgsm_perturb(model, x_cont[idx], x_cat[idx], labels[idx], loss_fn)
                adv_logits = model(adv_x_cont, x_cat[idx])
                adv_loss = loss_fn(adv_logits, labels[idx])

                loss = clean_loss + adv_loss
                loss.backward()
                opt.step()

        self.last_val_accuracy = self._evaluate(model, self.val_buffer)
        return model.adapter_state_dict()

    def _batch(self, buffer=None):
        buffer = buffer if buffer is not None else self.local_buffer
        x_cont = torch.stack([r[0] for r in buffer]).to(self.device)
        x_cat = torch.stack([r[1] for r in buffer]).to(self.device)
        labels = torch.tensor([r[2] for r in buffer]).to(self.device)
        return x_cont, x_cat, labels

    def _evaluate(self, model, buffer):
        if not buffer:
            return 0.0
        model.eval()
        with torch.no_grad():
            x_cont, x_cat, labels = self._batch(buffer)
            preds = model(x_cont, x_cat).argmax(dim=-1)
            return (preds == labels).float().mean().item()
