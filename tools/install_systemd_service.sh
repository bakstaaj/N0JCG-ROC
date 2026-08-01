#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_SOURCE="${PROJECT_DIR}/deploy/n0jcg-roc.service"
SERVICE_TARGET="/etc/systemd/system/n0jcg-roc.service"

if [[ "$(id -un)" != "n0jcg" ]]; then
  echo 'FINAL: FAIL - run from the n0jcg account'
  exit 1
fi

if [[ "${PROJECT_DIR}" != "/home/n0jcg/sdrdev/N0JCG-ROC" ]]; then
  echo "FINAL: FAIL - expected project at /home/n0jcg/sdrdev/N0JCG-ROC"
  exit 1
fi

python3 -m compileall -q "${PROJECT_DIR}/src"
sudo install -o root -g root -m 0644 "${SERVICE_SOURCE}" "${SERVICE_TARGET}"
sudo systemctl daemon-reload
sudo systemctl enable --now n0jcg-roc.service

for attempt in 1 2 3 4 5; do
  if curl -fsS http://127.0.0.1:8095/api/health >/dev/null; then
    systemctl --no-pager --full status n0jcg-roc.service
    echo 'FINAL: PASS'
    exit 0
  fi
  sleep 1
done

systemctl --no-pager --full status n0jcg-roc.service || true
journalctl -u n0jcg-roc.service -n 50 --no-pager || true
echo 'FINAL: FAIL - service did not become ready'
exit 1
