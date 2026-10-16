#!/bin/bash
# $1 = seed. Waits for exp10 jobs, then reruns the agent sim with the exception-TTL configs.
cd /opt/fedgrid/exp10
aws s3 cp s3://fedgrid-weightsbucket-kwh3ffbpsq5a/deploy/agent_policy_experiment.py cloud/agent_policy_experiment.py --region ap-south-1 --quiet
until grep -q ALLDONE all.log 2>/dev/null; do sleep 20; done
sudo systemctl stop fedgrid-agent || true
source /opt/fedgrid/venv/bin/activate
export PYTHONPATH=/opt/fedgrid/exp10:/opt/fedgrid/exp10/cloud TMPDIR=/opt/fedgrid/tmp
for st in ton unsw; do python -m cloud.agent_policy_experiment $st $1 2>&1 | grep -E "^RESULT|Error|Killed"; done > agent11.log
echo AGENT11DONE >> agent11.log
sudo systemctl start fedgrid-agent || true
