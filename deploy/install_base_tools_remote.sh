#!/usr/bin/env bash
set -euo pipefail

ROC_HOST="${ROC_HOST:-192.168.68.145}"
ROC_USER="${ROC_USER:-n0jcg}"
ROC_REMOTE_DIR="${ROC_REMOTE_DIR:-/home/n0jcg/sdrdev/N0JCG-ROC}"
ROC_IDENTITY_FILE="${ROC_IDENTITY_FILE:-${HOME}/.ssh/n0jcg_roc_ed25519}"
MODE=install

if [[ "${1:-}" == '--check-only' ]]; then
  MODE=check
elif [[ $# -ne 0 ]]; then
  echo 'Usage: install_base_tools_remote.sh [--check-only]'
  exit 2
fi

[[ "${ROC_REMOTE_DIR}" == '/home/n0jcg/sdrdev/N0JCG-ROC' ]] || {
  echo 'FINAL: FAIL - unexpected ROC_REMOTE_DIR'
  exit 1
}
[[ -f "${ROC_IDENTITY_FILE}" ]] || { echo 'FINAL: FAIL - deployment SSH key missing'; exit 1; }
SSH=(ssh -i "${ROC_IDENTITY_FILE}" -o BatchMode=yes -o ConnectTimeout=8)

if [[ "${MODE}" == check ]]; then
  "${SSH[@]}" "${ROC_USER}@${ROC_HOST}" "cd '${ROC_REMOTE_DIR}' && ./tools/install_base_tools.sh --check-only"
  exit 0
fi

[[ -n "${ROC_SUDO_PASS:-}" ]] || { echo 'FINAL: FAIL - set ROC_SUDO_PASS transiently'; exit 1; }
printf '%s\n' "${ROC_SUDO_PASS}" | "${SSH[@]}" "${ROC_USER}@${ROC_HOST}" "sudo -S -p '' -v && cd '${ROC_REMOTE_DIR}' && ./tools/install_base_tools.sh"
