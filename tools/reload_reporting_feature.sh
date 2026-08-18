#!/usr/bin/env bash
set -euo pipefail

touch /var/lib/n0jcg-roc/admin-report-credentials-ready
chmod 0640 /var/lib/n0jcg-roc/admin-report-credentials-ready

for service in n0jcg-roc.service n0jcg-admin-report.service; do
  pid="$(systemctl show -p MainPID --value "${service}")"
  [[ "${pid}" =~ ^[1-9][0-9]*$ ]] || { echo "FINAL: FAIL - ${service} has no running process"; exit 1; }
  kill -TERM "${pid}"
done

for _attempt in {1..20}; do
  if systemctl is-active --quiet n0jcg-roc.service n0jcg-admin-report.service; then
    echo 'FINAL: PASS - ROC and operator report worker reloaded'
    exit 0
  fi
  sleep 0.5
done

echo 'FINAL: FAIL - services did not return active'
exit 1
