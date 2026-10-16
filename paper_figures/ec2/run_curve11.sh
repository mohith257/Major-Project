#!/bin/bash
# exp11: frozen-backbone threshold points at the FPRs the exp11 variants end at
cd /opt/fedgrid/exp11
aws s3 cp s3://fedgrid-weightsbucket-kwh3ffbpsq5a/deploy/operating_curve.py model/operating_curve.py --region ap-south-1 --quiet
source /opt/fedgrid/venv/bin/activate
export PYTHONPATH=/opt/fedgrid/exp11 TMPDIR=/opt/fedgrid/tmp
sudo systemctl stop fedgrid-agent || true
{ python -m model.operating_curve 2>&1 | tail -2; echo CURVEDONE; } > curve.log
sudo systemctl start fedgrid-agent || true
