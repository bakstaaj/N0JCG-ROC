#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${SUDO_USER:-}" || "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo 'FINAL: FAIL - run setup_server_auth.sh as the development user, not with sudo'
  exit 1
fi

ROC_HOST="${ROC_HOST:-192.168.68.114}"
ROC_USER="${ROC_USER:-n0jcg}"
ROC_IDENTITY_FILE="${ROC_IDENTITY_FILE:-${HOME}/.ssh/n0jcg_roc_ed25519}"

if [[ ! "${ROC_HOST}" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo 'FINAL: FAIL - invalid ROC_HOST'
  exit 1
fi
if [[ ! "${ROC_USER}" =~ ^[a-z_][a-z0-9_-]*$ ]]; then
  echo 'FINAL: FAIL - invalid ROC_USER'
  exit 1
fi

mkdir -p "$(dirname "${ROC_IDENTITY_FILE}")"
chmod 700 "$(dirname "${ROC_IDENTITY_FILE}")"

if [[ ! -f "${ROC_IDENTITY_FILE}" ]]; then
  ssh-keygen -q -t ed25519 -N '' -C 'n0jcg-roc-deployment' -f "${ROC_IDENTITY_FILE}"
fi

if ssh -i "${ROC_IDENTITY_FILE}" -o BatchMode=yes -o ConnectTimeout=8 "${ROC_USER}@${ROC_HOST}" true 2>/dev/null; then
  echo 'PASS SSH key already authorized'
elif [[ -n "${ROC_PASS:-}" ]]; then
  SSHPASS="${ROC_PASS}" sshpass -e ssh-copy-id -i "${ROC_IDENTITY_FILE}.pub" "${ROC_USER}@${ROC_HOST}"
else
  echo 'FINAL: FAIL - set ROC_PASS transiently to authorize the new key'
  exit 1
fi

ssh -i "${ROC_IDENTITY_FILE}" -o BatchMode=yes -o ConnectTimeout=8 "${ROC_USER}@${ROC_HOST}" 'printf "HOST=%s USER=%s\n" "$(hostname)" "$(id -un)"'
echo 'FINAL: PASS'
