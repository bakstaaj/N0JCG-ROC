#!/usr/bin/env bash
set -euo pipefail

ROC_HOST="${ROC_HOST:-192.168.68.145}"
ROC_USER="${ROC_USER:-n0jcg}"
ROC_IDENTITY_FILE="${ROC_IDENTITY_FILE:-${HOME}/.ssh/n0jcg_roc_ed25519}"
REMOTE_DIR='/home/n0jcg/sdrdev/N0JCG-ROC'
SERVICE_FILE='/etc/systemd/system/n0jcg-roc.service'

[[ "${1:-}" == '--stop-only' || $# -eq 0 ]] || { echo 'Usage: undeploy.sh [--stop-only]'; exit 2; }
[[ -n "${ROC_SUDO_PASS:-}" ]] || { echo 'FINAL: FAIL - set ROC_SUDO_PASS transiently'; exit 1; }
SSH=(ssh -i "${ROC_IDENTITY_FILE}" -o BatchMode=yes -o ConnectTimeout=8)

printf '%s\n' "${ROC_SUDO_PASS}" | "${SSH[@]}" "${ROC_USER}@${ROC_HOST}" "sudo -S -p '' systemctl disable --now n0jcg-roc.service"
if [[ "${1:-}" == '--stop-only' ]]; then
  echo 'FINAL: PASS - service stopped; files retained'
  exit 0
fi

[[ "${CONFIRM_REMOVE:-}" == YES ]] || { echo 'FINAL: FAIL - set CONFIRM_REMOVE=YES for full removal'; exit 1; }
"${SSH[@]}" "${ROC_USER}@${ROC_HOST}" "test \"${REMOTE_DIR}\" = /home/n0jcg/sdrdev/N0JCG-ROC && test -d \"${REMOTE_DIR}\""
printf '%s\n' "${ROC_SUDO_PASS}" | "${SSH[@]}" "${ROC_USER}@${ROC_HOST}" "sudo -S -p '' rm -f '${SERVICE_FILE}' && sudo systemctl daemon-reload"
"${SSH[@]}" "${ROC_USER}@${ROC_HOST}" "rm -rf -- '${REMOTE_DIR}'"
echo 'FINAL: PASS - ROC-owned service and project directory removed'
