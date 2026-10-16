# Section V: Results (LaTeX, compact: 7 tables, 3 figures)

Paste the code block below into your `.tex` file, right after Section IV (Experimental Setup).

## Before it compiles

1. Add `\usepackage{booktabs}` to the preamble (next to `\usepackage{graphicx}`).
2. Put `fig2_rounds.png`, `fig3_ablation_bars.png` and `fig4_agent_bars.png` in the same folder as your `.tex` file.
3. In Section III (Flow representation and backbone), replace `(Table~\ref{tab:fed_rounds_v2})` with `(Section~V-B)`; that table no longer exists.
4. Compile twice so table and figure numbers resolve.

## Code

```latex
\section{Results}

\subsection{Backbone and reference models}
Table~\ref{tab:backbone} reports the frozen backbone before any federation.
Moving from one token for all continuous features (v1) to one token per
feature with a longer one-cycle schedule (v2) raises UNSW-NB15 accuracy from
87.19\% to 87.73$\pm$0.35\%, lowers its FPR from 14.31\% to
12.94$\pm$1.13\%, and lifts ToN\_IoT to 99.28$\pm$0.04\% (FPR 1.64\%).
Inference stays at 1.7\,ms per flow on a t3.small. The better general fit
comes with lower recall on the withheld Fuzzers class before federation
(36.81\% vs.\ 41.06\%), so v2 is not uniformly better.

\begin{table}[t]\centering
\caption{Frozen backbone and reference models on the official UNSW-NB15 test set (82{,}332 flows) and the ToN\_IoT held-out split (31{,}656 flows); same eight features, EC2. GBM = gradient-boosted trees. Mean $\pm$ sd over 3 seeds where shown (v1 frozen: single run; federated row: 4 seeds).}
\label{tab:backbone}
\resizebox{\columnwidth}{!}{\begin{tabular}{lcccc}\toprule
Model & UNSW acc. (\%) & UNSW FPR (\%) & Fuzzers rec. (\%) & ToN acc. (\%) \\ \midrule
GBM (Fuzzers excluded) & 90.10 $\pm$ 0.17 & 8.92 $\pm$ 0.40 & 34.27 $\pm$ 0.25 & 99.55 $\pm$ 0.01 \\
Centralized Transformer (Fuzzers incl.) & 82.39 $\pm$ 0.45 & 36.38 $\pm$ 1.65 & 89.76 $\pm$ 1.74 & 98.88 $\pm$ 0.07 \\
Backbone v1, frozen & 87.19 & 14.31 & 41.06 & 98.84 \\
Backbone v2, frozen & 87.73 $\pm$ 0.35 & 12.94 $\pm$ 1.13 & 36.81 $\pm$ 0.81 & 99.28 $\pm$ 0.04 \\
Backbone v1 + 4 LoRA rounds & 86.46 $\pm$ 0.07 & 19.21 $\pm$ 0.61 & 54.50 $\pm$ 1.92 & -- \\
\bottomrule\end{tabular}}\end{table}

Table~\ref{tab:backbone} also places the backbone between two references trained on
the same eight features. Gradient-boosted trees trained on the same
pretraining pool reach 90.10$\pm$0.17\% accuracy at 8.9\% FPR, so the
Transformer itself costs about 2.4 points on this split. We keep it because
LoRA federation, FGSM training and attention attribution all require a
differentiable model, and the tree's advantage does not extend to the unseen
class (34.3\% Fuzzers recall vs.\ 41.1\%). The backbone scores 97.9\% on a
random split of its own pretraining pool. The roughly 10-point drop to the
official test file is distribution shift between the official training and
test files, not a lack of fit. A Transformer trained
centrally on all device data, Fuzzers included, reaches 89.8\% Fuzzers recall
but only 82.4\% accuracy at 36.4\% FPR (3 seeds).

\subsection{Federated adaptation to an unseen attack class}
Fuzzers flows are excluded from pretraining and appear only on device~1,
revealed 25/50/75/100\% over four rounds. All metrics are measured on the
global model on device~2, which never sees a Fuzzers flow.

\textbf{At the default threshold} (Fig.~\ref{fig:rounds}), Fuzzers recall rises from 41.06\% to
54.50$\pm$1.92\% (backbone v1, 4 seeds) and replay-set accuracy from 28.14\% to
43.53\%. Accuracy moves only from 87.19\% to 86.46\%, but the FPR rises from
14.31\% to 19.21\%. Backbone v2 gives 36.81\%~$\rightarrow$~47.39$\pm$9.83\%
at 17.01\% FPR (3 seeds).

\begin{figure}[t]\centering
\includegraphics[width=\columnwidth]{fig2_rounds.png}
\caption{Global model per FedAvg round on device~2 (never sees Fuzzers locally): Fuzzers recall at the default threshold (left) and UNSW-NB15 FPR (right), mean $\pm$ sd over seeds, EC2. Both rise together; moving the frozen backbone's threshold to the same FPR gives the same recall (Table~\ref{tab:threshold}).}
\label{fig:rounds}
\end{figure}

\textbf{Threshold-free} (Tables~\ref{tab:operating},~\ref{tab:threshold}), the
picture changes. Across rounds, AUROC stays at 0.962~$\rightarrow$~0.959, the
Fuzzers-vs-benign AUROC at 0.823~$\rightarrow$~0.818, and Fuzzers recall at a
fixed 10\% FPR falls from 38.0\% to 34.8\%. Moving only the frozen backbone's
threshold to the FPR each federated variant ends at gives the same recall:
53.4\% vs.\ 54.5\% at 19.2\% FPR, 51.6\% vs.\ 50.5\% at 18.3\%, and 57.0\% vs.\
59.1\% at 21.2\%. Federation in this setting therefore moves the operating
point toward ``attack''; it does not teach the model to separate Fuzzers from
benign traffic. The information is not absent. The centrally trained model
reaches 0.847 Fuzzers AUROC and 48.1\% recall at 10\% FPR (one seed).

\begin{table}[t]\centering
\caption{Threshold-free view of federation (official UNSW-NB15 test set, 3 seeds; EC2): AUROC over all flows, Fuzzers-vs-benign AUROC, and Fuzzers recall at a fixed 10\% benign FPR (threshold set on the benign test flows), before and after 4 rounds.}
\label{tab:operating}
\resizebox{\columnwidth}{!}{\begin{tabular}{lccc}\toprule
Variant (round 4 unless stated) & AUROC & Fuzzers AUROC & Fuzzers rec.\ @10\% FPR (\%) \\ \midrule
Before federation (round 0) & 0.962 $\pm$ 0.000 & 0.823 $\pm$ 0.000 & 37.99 $\pm$ 0.00 \\
LoRA $r{=}4$ (default) & 0.959 $\pm$ 0.001 & 0.818 $\pm$ 0.003 & 34.83 $\pm$ 1.40 \\
LoRA $r{=}8$ & 0.958 $\pm$ 0.001 & 0.818 $\pm$ 0.003 & 34.40 $\pm$ 1.45 \\
Full-model FedAvg & 0.950 $\pm$ 0.003 & 0.809 $\pm$ 0.003 & 30.19 $\pm$ 0.51 \\
Median aggregation & 0.959 $\pm$ 0.001 & 0.817 $\pm$ 0.001 & 34.63 $\pm$ 0.98 \\
Fuzzers on 2 clients & 0.959 $\pm$ 0.001 & 0.818 $\pm$ 0.001 & 34.69 $\pm$ 0.60 \\
Fuzzers on 3 clients & 0.957 $\pm$ 0.000 & 0.818 $\pm$ 0.001 & 34.48 $\pm$ 0.31 \\
5$\times$ local steps & 0.956 $\pm$ 0.002 & 0.817 $\pm$ 0.001 & 33.77 $\pm$ 0.86 \\
3 clients + 5$\times$ steps & 0.826 $\pm$ 0.115 & 0.820 $\pm$ 0.006 & 36.12 $\pm$ 2.98 \\
\bottomrule\end{tabular}}\end{table}

\begin{table}[t]\centering
\caption{Federated Fuzzers recall vs.\ the frozen backbone with only its decision threshold moved to the same benign FPR (official UNSW-NB15 test set; EC2). The frozen model needs no federation at all.}
\label{tab:threshold}
\resizebox{\columnwidth}{!}{\begin{tabular}{lccc}\toprule
Federated model & FPR (\%) & Fuzzers rec.\ (\%) & Frozen, threshold moved (\%) \\ \midrule
LoRA $r{=}4$, 4 rounds & 18.28 $\pm$ 0.83 & 50.48 $\pm$ 3.16 & 51.62 \\
LoRA $r{=}4$, Lambda path (4 seeds) & 19.21 $\pm$ 0.61 & 54.50 $\pm$ 1.92 & 53.37 \\
LoRA $r{=}8$, 4 rounds & 21.24 $\pm$ 2.66 & 59.12 $\pm$ 6.45 & 56.96 \\
Full-model FedAvg, 4 rounds & 33.08 $\pm$ 1.80 & 78.04 $\pm$ 3.34 & 84.00 \\
Fuzzers on 2 clients, 4 rounds & 18.47 $\pm$ 2.19 & 51.15 $\pm$ 6.93 & 51.93 \\
5$\times$ local steps, 4 rounds & 28.24 $\pm$ 6.83 & 71.41 $\pm$ 11.17 & 71.68 \\
Fuzzers on 3 clients, 4 rounds & 33.56 $\pm$ 0.83 & 79.42 $\pm$ 1.40 & 85.09 \\
3 clients + 5$\times$ steps, 4 rounds & 37.36 $\pm$ 1.44 & 87.19 $\pm$ 4.38 & 89.69 \\
\bottomrule\end{tabular}}\end{table}

\textbf{More clients and longer local training.} Two obvious explanations
are that only one of four clients holds the class and that each round runs
only 100 local steps. We tested both on the same Fuzzers flows: split into
disjoint shards over two or three clients, with 5$\times$ more local steps
(500 per round), and both combined (Tables~\ref{tab:ablation},~\ref{tab:operating},~\ref{tab:threshold};
3 seeds each). Default-threshold recall rises to 51.1\% (two clients),
71.4\% (5$\times$ steps), 79.4\% (three clients) and 87.2\% (both), but the
FPR rises with it, to 18.5\%, 28.2\%, 33.6\% and 37.4\%. The Fuzzers-vs-benign
AUROC stays at 0.817--0.820 in every variant (0.823 before federation), and
recall at 10\% FPR stays at 33.8--36.1\% (38.0\% before). The frozen backbone
with only its threshold moved to the same FPR matches or beats each variant:
51.9\% vs.\ 51.1\%, 71.7\% vs.\ 71.4\%, 85.1\% vs.\ 79.4\%, and 89.7\% vs.\
87.2\%. Longer local training also costs robustness (FGSM accuracy 74.5\%
$\rightarrow$ 53.9\%), and with three clients and 5$\times$ steps two of three
seeds collapse (UNSW accuracy 59.8\% and 59.6\%, AUROC 0.77 and 0.75).
Participation and local budget are therefore not the bottleneck in the regimes
we tested. Together with the full-model result below, which removes the
capacity limit and degrades the ranking further, this suggests that the
binary local objective itself moves the decision boundary rather than the
representation. We regard default-threshold recall as an unreliable measure
of federated gains and report both.

\subsection{Ablations}
Table~\ref{tab:ablation} and Fig.~\ref{fig:ablation} vary one component at a
time. Unless stated otherwise, each variant uses backbone v1, LoRA $r{=}4$ and
FedAvg, with 3 seeds.

\begin{table*}[t]\centering
\caption{Ablations after 4 federated rounds, global model on device 2 (mean $\pm$ sd over 3 seeds; EC2). Payload = raw float32 bytes uploaded per device per round. Adv.\ acc.\ = accuracy under FGSM, $\epsilon{=}0.05$, 5{,}000 test flows.}
\label{tab:ablation}
\resizebox{\textwidth}{!}{\begin{tabular}{lrcccccc}\toprule
Variant & Payload (B) & Fuzzers rec. (\%) & UNSW acc. (\%) & UNSW FPR (\%) & Macro-F1 & Adv. acc. (\%) & ToN acc. (\%) \\ \midrule
LoRA $r{=}1$ & 2,835 & 51.25 $\pm$ 1.71 & 86.67 $\pm$ 0.13 & 18.26 $\pm$ 0.69 & 0.864 $\pm$ 0.001 & 73.82 $\pm$ 1.64 & 98.90 $\pm$ 0.04 \\
LoRA $r{=}2$ & 5,403 & 52.42 $\pm$ 0.11 & 86.55 $\pm$ 0.14 & 18.66 $\pm$ 0.30 & 0.863 $\pm$ 0.001 & 73.50 $\pm$ 1.48 & 98.87 $\pm$ 0.01 \\
LoRA $r{=}4$ (default) & 10,515 & 50.48 $\pm$ 3.16 & 86.47 $\pm$ 0.04 & 18.28 $\pm$ 0.83 & 0.862 $\pm$ 0.001 & 74.49 $\pm$ 0.15 & 98.19 $\pm$ 1.09 \\
LoRA $r{=}8$ & 20,763 & 59.12 $\pm$ 6.45 & 86.00 $\pm$ 0.56 & 21.24 $\pm$ 2.66 & 0.857 $\pm$ 0.007 & 75.21 $\pm$ 1.07 & 97.72 $\pm$ 0.97 \\
Full-model FedAvg & 106,155 & 78.04 $\pm$ 3.34 & 82.66 $\pm$ 0.40 & 33.08 $\pm$ 1.80 & 0.817 $\pm$ 0.005 & 59.13 $\pm$ 13.48 & 95.95 $\pm$ 2.51 \\
w/o hard-example mining & 10,515 & 52.97 $\pm$ 2.58 & 86.62 $\pm$ 0.02 & 18.65 $\pm$ 0.70 & 0.864 $\pm$ 0.000 & 58.71 $\pm$ 12.80 & 98.81 $\pm$ 0.05 \\
w/o FGSM training & 10,515 & 50.26 $\pm$ 0.15 & 86.78 $\pm$ 0.03 & 17.67 $\pm$ 0.12 & 0.866 $\pm$ 0.000 & 52.37 $\pm$ 0.37 & 99.11 $\pm$ 0.01 \\
FedProx ($\mu{=}0.01$) & 10,515 & 52.42 $\pm$ 3.88 & 86.37 $\pm$ 0.10 & 18.98 $\pm$ 1.13 & 0.861 $\pm$ 0.001 & 74.56 $\pm$ 0.16 & 98.81 $\pm$ 0.01 \\
Median aggregation & 10,515 & 56.84 $\pm$ 3.00 & 86.31 $\pm$ 0.15 & 20.14 $\pm$ 1.02 & 0.860 $\pm$ 0.002 & 75.01 $\pm$ 0.89 & 98.21 $\pm$ 1.05 \\
+ adoption gate & 10,515 & 48.88 $\pm$ 4.95 & 86.47 $\pm$ 0.12 & 17.83 $\pm$ 1.43 & 0.863 $\pm$ 0.002 & 74.58 $\pm$ 0.34 & 98.18 $\pm$ 1.08 \\
Poisoned client, FedAvg & 10,515 & 76.20 $\pm$ 41.22 & 47.51 $\pm$ 13.08 & 81.25 $\pm$ 32.47 & 0.337 $\pm$ 0.031 & 44.79 $\pm$ 15.57 & 72.06 $\pm$ 7.36 \\
Poisoned client, FedAvg + gate & 10,515 & 88.56 $\pm$ 3.51 & 81.32 $\pm$ 0.69 & 38.82 $\pm$ 2.34 & 0.799 $\pm$ 0.009 & 76.29 $\pm$ 1.14 & 89.56 $\pm$ 0.31 \\
Poisoned client, median & 10,515 & 50.86 $\pm$ 6.05 & 86.54 $\pm$ 0.21 & 18.46 $\pm$ 2.20 & 0.863 $\pm$ 0.003 & 69.16 $\pm$ 13.43 & 98.67 $\pm$ 0.03 \\
Fuzzers on 2 clients & 10,515 & 51.15 $\pm$ 6.93 & 86.46 $\pm$ 0.22 & 18.47 $\pm$ 2.19 & 0.862 $\pm$ 0.003 & 74.36 $\pm$ 0.52 & 98.22 $\pm$ 1.02 \\
Fuzzers on 3 clients & 10,515 & 79.42 $\pm$ 1.40 & 82.72 $\pm$ 0.22 & 33.56 $\pm$ 0.83 & 0.818 $\pm$ 0.003 & 77.03 $\pm$ 0.27 & 98.78 $\pm$ 0.02 \\
5$\times$ local steps & 10,515 & 71.41 $\pm$ 11.17 & 84.15 $\pm$ 1.92 & 28.24 $\pm$ 6.83 & 0.835 $\pm$ 0.022 & 53.93 $\pm$ 1.34 & 97.10 $\pm$ 0.08 \\
3 clients + 5$\times$ steps & 10,515 & 87.19 $\pm$ 4.38 & 67.04 $\pm$ 12.69 & 37.36 $\pm$ 1.44 & 0.665 $\pm$ 0.119 & 54.24 $\pm$ 2.40 & 97.63 $\pm$ 1.09 \\
\bottomrule\end{tabular}}\end{table*}

\begin{figure*}[t]\centering
\includegraphics[width=0.9\textwidth]{fig3_ablation_bars.png}
\caption{Ablations after four rounds (3 seeds, EC2). Labels give the upload size per device per round. Poisoning results are in Table~\ref{tab:ablation}.}
\label{fig:ablation}
\end{figure*}

\textbf{Rank and full-model federation.} Ranks 1, 2 and 4 behave almost
identically: Fuzzers recall 50.5--52.4\%, FPR $\approx$18.3\%, at 2.8--10.3\,KB
per upload. Rank 8 (20.3\,KB) reaches 59.1\% at 21.2\% FPR. Full-model FedAvg
sends 10$\times$ more data (103.7\,KB) and reaches 78.0\% recall at 33.1\% FPR.
Threshold-free, the full model is worse: AUROC 0.950 vs.\ 0.959 for LoRA,
30.2\% vs.\ 34.8\% Fuzzers recall at 10\% FPR, and 78.0\% vs.\ 84.0\% for the
frozen backbone at the same 33.1\% FPR. Updating every weight from one
site's skewed data degrades the shared ranking. The low-rank restriction
limits this degradation, but it does not produce a gain either.

\textbf{Local objective.} FedProx ($\mu{=}0.01$) gives no measurable gain over
FedAvg: 52.4\% vs.\ 50.5\% recall and 19.0\% vs.\ 18.3\% FPR, both within
one standard deviation. This is consistent with the already bounded local
update, which limits client drift without a proximal term.

\textbf{Training components.} Removing FGSM training leaves clean accuracy
essentially unchanged (86.78\% vs.\ 86.47\%). Accuracy under an FGSM
perturbation ($\epsilon{=}0.05$) falls from 74.49\% to 52.37\%. Removing
hard-example mining does not change Fuzzers recall (52.97\%), but robustness
becomes unstable across seeds (58.7$\pm$12.8\%). We report mining as having
no clear benefit.

\textbf{Poisoning.} One client uploads $-10\times$ its honest adapter
(model replacement). Under FedAvg the global model collapses to near-chance
accuracy (47.5$\pm$13.1\%), alternating between labelling everything benign
and everything malicious. With the adoption gate, every device rejected every
poisoned global model in all rounds and seeds. However, the isolated devices
keep training only on their own skewed data, and device~2's FPR drifts to
38.8\%. Coordinate-wise median aggregation removes the attack at the server:
86.54$\pm$0.21\% accuracy and 18.46$\pm$2.20\% FPR, matching the clean runs.
Median aggregation on clean data costs little (86.31\% accuracy, 20.1\% FPR;
AUROC 0.959, identical to FedAvg). The two defences are complementary: the
median protects the shared model, and the gate protects a device if the
server is compromised.

\subsection{The agentic decision layer}
\textbf{Action selection} (Table~\ref{tab:policy}).
On UNSW-NB15, the cost-aware rule cuts missed attacks from 11.6\% to 2.4\% of
attack flows and lowers the average cost per flow by 23\%. The price is that
it alerts on 31.5\% of benign flows instead of 12.6\%, which means more
analyst workload. On ToN\_IoT both rules are already near-perfect, and the
cost rule halves missed attacks (0.92\%~$\rightarrow$~0.39\%).

\begin{table}[t]\centering
\caption{Per-flow decisions of the frozen model under the default cost table (deterministic; sd $=0$).}
\label{tab:policy}
\resizebox{\columnwidth}{!}{\begin{tabular}{llcccc}\toprule
Data & Policy & False block (\%) & Benign alert (\%) & Attack missed (\%) & Cost/flow \\ \midrule
UNSW & Threshold ($p\geq0.9$) & 1.69 & 12.62 & 11.59 & 1.012 \\
UNSW & Cost-aware (Bayes) & 2.31 & 31.53 & 2.36 & 0.776 \\
ToN & Threshold ($p\geq0.9$) & 1.24 & 0.69 & 0.92 & 0.152 \\
ToN & Cost-aware (Bayes) & 1.28 & 2.40 & 0.39 & 0.126 \\
\bottomrule\end{tabular}}\end{table}

\textbf{Response and learning} (Table~\ref{tab:agent};
Fig.~\ref{fig:agent}). Blocking per source IP magnifies false positives: one
wrong verdict on a busy benign host cuts off all of its later traffic. With
permanent blocks (configuration A) this drops 49.8\% of benign ToN\_IoT flows
and 22.1\% of benign UNSW-NB15 flows.
\begin{itemize}
\item Graded, self-expiring blocks (C) reduce this to 28.6\% and 1.4\%,
without any analyst.
\item Analyst rollback with learned exceptions (D) reduces it further, to 9.4\% and 1.2\%.
\item Peer intelligence with retraction (E) costs a little benign traffic
(12.5\% and 2.1\%) but stops more attacks. Attack flows that get through fall
from 0.029\% to 0.019\% (ToN\_IoT) and from 0.38\% to 0.13\% (UNSW-NB15)
relative to the threshold-and-block baseline.
\end{itemize}
With an oracle analyst, the full agent therefore dominates the baseline on
both axes and both datasets.

\begin{table*}[t]\centering
\caption{Four-agent stream simulation (3 seeds; EC2; oracle analyst). Dropped = benign flows refused by an active block; unblocked = attack flows not blocked or dropped. ToN\_IoT uses real source IPs; UNSW-NB15 uses synthetic sessions.}
\label{tab:agent}
\resizebox{\textwidth}{!}{\begin{tabular}{lcccc}\toprule
 & \multicolumn{2}{c}{ToN\_IoT} & \multicolumn{2}{c}{UNSW-NB15} \\
Agent configuration & Benign dropped (\%) & Attack unblocked (\%) & Benign dropped (\%) & Attack unblocked (\%) \\ \midrule
A: threshold rule, permanent block & 49.79 $\pm$ 7.13 & 0.029 $\pm$ 0.008 & 22.05 $\pm$ 0.60 & 0.381 $\pm$ 0.044 \\
B: cost-aware, permanent block & 51.07 $\pm$ 6.75 & 0.028 $\pm$ 0.006 & 28.35 $\pm$ 0.62 & 0.285 $\pm$ 0.022 \\
C: + graded blocks (TTL) & 28.63 $\pm$ 5.67 & 0.083 $\pm$ 0.021 & 1.42 $\pm$ 0.06 & 1.267 $\pm$ 0.119 \\
D: + analyst rollback \& exceptions & 9.40 $\pm$ 0.70 & 0.072 $\pm$ 0.013 & 1.21 $\pm$ 0.02 & 1.113 $\pm$ 0.160 \\
E: + peer intel w/ retraction (full) & 12.50 $\pm$ 1.91 & 0.019 $\pm$ 0.005 & 2.14 $\pm$ 0.08 & 0.132 $\pm$ 0.032 \\
\bottomrule\end{tabular}}\end{table*}

\begin{figure*}[t]\centering
\includegraphics[width=0.9\textwidth]{fig4_agent_bars.png}
\caption{Agent configurations A (threshold, permanent block) to E (full agent): benign flows dropped and attack flows not blocked, four agents, 3 seeds.}
\label{fig:agent}
\end{figure*}

\textbf{Imperfect analyst} (Table~\ref{tab:analyst}). In the next experiment,
the analyst reviews only a random half of the blocks and is wrong 10\% or
20\% of the time. Benign traffic dropped stays well below the baseline
(24.0\% vs.\ 49.8\% on ToN\_IoT, 4.1\% vs.\ 22.1\% on UNSW-NB15 at 10\% error).
Attack leakage, however, grows sharply: 4.5\% of ToN\_IoT attack flows get
through at 10\% error and 11.8\% at 20\% error, against 0.083\% for
configuration C with no analyst at all. The cause is the learned exception. A
single wrong rollback of an attacker grants it 30 minutes in which block
verdicts are downgraded to alerts, and the retraction propagates to every
peer. Shortening the exception to 5 minutes cuts the leakage by about
two-thirds (4.5\%~$\rightarrow$~1.5\% on ToN\_IoT and 3.1\%~$\rightarrow$~1.1\%
on UNSW-NB15 at 10\% error). It costs more benign blocking with an ideal
analyst (12.5\%~$\rightarrow$~18.6\% on ToN\_IoT). Analyst feedback is only
worth enabling where analyst verdicts are reliable. Otherwise graded blocks
alone (C) are the safer configuration.

\begin{table*}[t]\centering
\caption{Sensitivity of the full agent to the analyst (3 seeds; EC2). The analyst reviews a random 50\% of blocks and gives the wrong verdict with the stated probability; a wrong verdict on an attacker rolls its block back and grants it the learned exception.}
\label{tab:analyst}
\resizebox{\textwidth}{!}{\begin{tabular}{lcccc}\toprule
 & \multicolumn{2}{c}{ToN\_IoT} & \multicolumn{2}{c}{UNSW-NB15} \\
Configuration & Benign dropped (\%) & Attack unblocked (\%) & Benign dropped (\%) & Attack unblocked (\%) \\ \midrule
C: no analyst & 28.63 $\pm$ 5.67 & 0.083 $\pm$ 0.021 & 1.42 $\pm$ 0.06 & 1.267 $\pm$ 0.119 \\
E: oracle analyst, 30-min exception & 12.50 $\pm$ 1.91 & 0.019 $\pm$ 0.005 & 2.14 $\pm$ 0.08 & 0.132 $\pm$ 0.032 \\
E: 50\% reviewed, 10\% wrong & 23.97 $\pm$ 4.54 & 4.543 $\pm$ 1.583 & 4.05 $\pm$ 0.32 & 3.067 $\pm$ 1.217 \\
E: 50\% reviewed, 20\% wrong & 31.77 $\pm$ 8.34 & 11.785 $\pm$ 3.186 & 4.13 $\pm$ 0.27 & 12.362 $\pm$ 1.731 \\
E: oracle, 5-min exception & 18.56 $\pm$ 1.58 & 0.018 $\pm$ 0.006 & 2.38 $\pm$ 0.10 & 0.132 $\pm$ 0.032 \\
E: 10\% wrong, 5-min exception & 29.16 $\pm$ 4.45 & 1.474 $\pm$ 0.228 & 4.25 $\pm$ 0.14 & 1.063 $\pm$ 0.396 \\
E: 20\% wrong, 5-min exception & 34.46 $\pm$ 6.44 & 4.893 $\pm$ 0.235 & 4.40 $\pm$ 0.36 & 3.049 $\pm$ 0.783 \\
\bottomrule\end{tabular}}\end{table*}
```
