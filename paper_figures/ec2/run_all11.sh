#!/bin/bash
# $@ = jobs: "<variant>:<seed>" (ablation) or "multi:<seed>" (moto multiround)
set -uo pipefail
D=/opt/fedgrid/exp11; REGION=ap-south-1
sudo systemctl stop fedgrid-agent || true
rm -rf $D && mkdir -p $D && cd $D
aws s3 cp s3://fedgrid-weightsbucket-kwh3ffbpsq5a/deploy/experiments11.tar.gz . --region $REGION --quiet && tar -xzf experiments11.tar.gz
source /opt/fedgrid/venv/bin/activate
export TMPDIR=/opt/fedgrid/tmp PYTHONUNBUFFERED=1 PYTHONPATH=$D:$D/cloud
for job in "$@"; do
  v=${job%%:*}; s=${job##*:}
  echo "### JOB $v $s $(hostname) $(date -u)"
  if [ "$v" = agent_ton ] || [ "$v" = agent_unsw ]; then
    python -m cloud.agent_policy_experiment ${v#agent_} $s > $D/${v}_$s.log 2>&1; rc=$?
    grep -E "^RESULT" $D/${v}_$s.log
  elif [ "$v" = baseline ]; then
    python -m model.train_baseline_centralized $s > $D/baseline_$s.log 2>&1; rc=$?
    grep -E "^RESULT_BASELINE" $D/baseline_$s.log
  elif [ "$v" = backbone ]; then
    python -m model.train_backbone $s > $D/backbone_$s.log 2>&1; rc=$?
    grep -E "^RESULT|epoch" $D/backbone_$s.log | tail -3
  elif [ "$v" = multi ]; then
    python -m cloud.multiround_fuzzers_experiment $s > $D/multi_$s.log 2>&1; rc=$?
    sed -n '/PROGRESSION SUMMARY/,$p' $D/multi_$s.log | sed "s/^/MULTI $s /"
  else
    python -m cloud.ablation_experiment $v $s > $D/abl_${v}_$s.log 2>&1; rc=$?
    grep -E "^RESULT" $D/abl_${v}_$s.log
  fi
  grep -E "Error|Killed|Traceback" $D/*_$s.log | tail -3
  echo "### END $v $s rc=$rc"
done > $D/all.log 2>&1
echo "### ALLDONE $(date -u)" >> $D/all.log
sudo systemctl start fedgrid-agent || true
