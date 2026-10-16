#!/bin/bash
cd /opt/fedgrid/exp10
aws s3 cp s3://fedgrid-weightsbucket-kwh3ffbpsq5a/deploy/gbm_reference.py model/gbm_reference.py --region ap-south-1 --quiet
aws s3 cp s3://fedgrid-weightsbucket-kwh3ffbpsq5a/deploy/central_pretrain_pool.csv data/processed/central_pretrain_pool.csv --region ap-south-1 --quiet
until grep -q ALLDONE all.log 2>/dev/null; do sleep 20; done
source /opt/fedgrid/venv/bin/activate
export PYTHONPATH=/opt/fedgrid/exp10 TMPDIR=/opt/fedgrid/tmp
for s in 0 1 2; do python -m model.gbm_reference $s 2>&1 | tail -3; done > gbm.log
echo GBMDONE >> gbm.log
