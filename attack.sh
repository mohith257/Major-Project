#!/usr/bin/env bash
# attack.sh - laptop-side attacker for the live remote-attack demo (Git Bash on Windows).
# Fires real TCP connections from THIS machine at the EC2 node's public IP over the internet.
# device-2's agent captures the SYNs on its real NIC, classifies them, and firewalls you.
#
# Usage (from Git Bash, in the project folder):
#   ./attack.sh                       # port scan against device-2 (3.109.0.101)
#   ./attack.sh 3.109.0.101 scan      # explicit
#   ./attack.sh 3.109.0.101 flood     # DoS-shaped SYN burst
#
# Uses curl (bundled with Git Bash) - no nmap needed. Each curl = one real TCP SYN at the target.
TARGET="${1:-3.109.0.101}"
MODE="${2:-scan}"

echo "=============================================================="
echo "  ATTACK  ->  this laptop  hitting EC2 node $TARGET  (mode=$MODE)"
echo "=============================================================="

if [ "$MODE" = "flood" ]; then
  echo "SYN flood: 300 rapid connects to :8080 ..."
  for i in $(seq 1 300); do curl -s -m1 -o /dev/null "http://$TARGET:8080/" & done
  wait
  echo "flood sent."
else
  for p in 21 22 23 25 53 80 110 135 139 143 443 445 1433 3306 3389 5432 8080 8443; do
    curl -s -m2 -o /dev/null "http://$TARGET:$p/" &
    echo "  SYN -> $TARGET:$p"
  done
  wait
  echo "scan sent."
fi

echo ""
echo "Now watch the agent react on device-2 (SSM session):  fg-watch"
echo "It will BLOCK your IP within a few seconds, with confidence + attention."
