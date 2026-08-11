#!/usr/bin/env bash
set -euo pipefail

# Run this from the development PC's MSYS2/UCRT64 shell. Passwords are read
# transiently and are never written to disk.
ROC_HOST="${ROC_HOST:-192.168.68.145}"
ROC_USER="${ROC_USER:-n0jcg}"
ROC_USB_IF="${ROC_USB_IF:-enx00e022adc83b}"
ROC_USB_ADDR="${ROC_USB_ADDR:-192.168.2.2/24}"
PLUTO_ADDR="${PLUTO_ADDR:-192.168.2.1}"
API_LOCAL_PORT="${API_LOCAL_PORT:-18085}"
SSH_LOCAL_PORT="${SSH_LOCAL_PORT:-10023}"

command -v ssh >/dev/null || { echo 'ERROR: ssh is required'; exit 1; }
command -v sshpass >/dev/null || { echo 'ERROR: install sshpass in MSYS2 first'; exit 1; }
command -v curl >/dev/null || { echo 'ERROR: curl is required'; exit 1; }

if [[ -z "${ROC_PASSWORD:-}" && -n "${SSHPASS:-}" ]]; then
  ROC_PASSWORD="${SSHPASS}"
fi
if [[ -z "${ROC_PASSWORD:-}" ]]; then
  read -r -s -p "ROC password: " ROC_PASSWORD
  printf '\n'
fi
export SSHPASS="${ROC_PASSWORD}"

SSH=(sshpass -e ssh -T -o StrictHostKeyChecking=no -o ConnectTimeout=8)

echo "Configuring ${ROC_USER}@${ROC_HOST}:${ROC_USB_IF} ..."
printf '%s\n' "${ROC_PASSWORD}" | ${SSH[@]} "${ROC_USER}@${ROC_HOST}" "sudo -S -p '' ip link set ${ROC_USB_IF} up"
printf '%s\n' "${ROC_PASSWORD}" | ${SSH[@]} "${ROC_USER}@${ROC_HOST}" "sudo -S -p '' ip addr replace ${ROC_USB_ADDR} dev ${ROC_USB_IF}"
${SSH[@]} "${ROC_USER}@${ROC_HOST}" "ping -c 2 -W 2 ${PLUTO_ADDR}"

if curl --fail --silent "http://127.0.0.1:${API_LOCAL_PORT}/system/health" >/dev/null 2>&1; then
  echo "Reusing working Pluto API tunnel on 127.0.0.1:${API_LOCAL_PORT}."
else
  echo "Opening Pluto API tunnel on 127.0.0.1:${API_LOCAL_PORT} ..."
  ${SSH[@]} -fN -o ExitOnForwardFailure=yes -L "${API_LOCAL_PORT}:${PLUTO_ADDR}:80" "${ROC_USER}@${ROC_HOST}"
fi

if command -v ss >/dev/null && ss -ltn "sport = :${SSH_LOCAL_PORT}" | grep -q LISTEN; then
  echo "Reusing existing Pluto SSH tunnel on 127.0.0.1:${SSH_LOCAL_PORT}."
else
  echo "Opening Pluto SSH tunnel on 127.0.0.1:${SSH_LOCAL_PORT} ..."
  ${SSH[@]} -fN -o ExitOnForwardFailure=yes -L "${SSH_LOCAL_PORT}:${PLUTO_ADDR}:22" "${ROC_USER}@${ROC_HOST}"
fi

sleep 1
curl --fail --silent --show-error "http://127.0.0.1:${API_LOCAL_PORT}/system/health" >/tmp/n0jcg-pluto-health.json
echo "Pluto bridge is ready. Health saved to /tmp/n0jcg-pluto-health.json"
echo "API: http://127.0.0.1:${API_LOCAL_PORT}"
echo "SSH: ssh -p ${SSH_LOCAL_PORT} root@127.0.0.1"
