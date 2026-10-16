#!/bin/bash
cd /opt/fedgrid/exp10
aws s3 cp s3://fedgrid-weightsbucket-kwh3ffbpsq5a/deploy/operating_curve.py model/operating_curve.py --region ap-south-1 --quiet
until grep -q GBMDONE gbm.log 2>/dev/null; do sleep 20; done
source /opt/fedgrid/venv/bin/activate
export PYTHONPATH=/opt/fedgrid/exp10 TMPDIR=/opt/fedgrid/tmp
{ python -m model.operating_curve 2>&1 | tail -2; python -m model.operating_curve model/baseline_centralized.pt 2>&1 | tail -2; echo CURVEDONE; } > curve.log
sudo systemctl start fedgrid-agent || true
