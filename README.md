# Agentic FedGrid

Autonomous, privacy-preserving network intrusion detection via federated
learning and agentic AI. Final year project, Dept. of ISE, JSSATE.

**Read `memory.md` first** — it's the running design doc: architecture,
dataset/partition plan, demo script, and the open TODO list. This README
is just orientation.

## Status

Scaffolding stage. Model + agent-controller code is written; cloud
infrastructure and dashboard are not yet started. Nothing runs end-to-end
until the datasets (UNSW-NB15 + ToN_IoT) are downloaded into `data/raw/`
and `data/scripts/partition_data.py`'s column mappings are verified
against the real CSV headers.

## Layout

See `memory.md` §9 for the current repo layout and what each module does.
