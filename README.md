# Agentic FedGrid

Autonomous, privacy-preserving network intrusion detection via federated
learning and agentic AI. Final year project, Dept. of ISE, JSSATE.

**Read `memory.md` first** — it's the running design doc: architecture,
dataset/partition plan, demo script, and the open TODO list. This README
is just orientation.

## Status

End-to-end and running for real. Datasets downloaded and partitioned,
backbone trained, cloud stack (`fedgrid`, ap-south-1) deployed via SAM,
dashboard built, and all 4 EC2 edge nodes are running the agent against
the live API (see `memory.md` §11g). Check `memory.md`'s Open TODOs (§10)
for what's still outstanding before the report/demo.

## Layout

See `memory.md` §9 for the current repo layout and what each module does.
