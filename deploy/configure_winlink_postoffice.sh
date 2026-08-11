#!/usr/bin/env bash
set -euo pipefail

MODE="${1:---enable}"
ENV_FILE="${WINLINK_ENV_FILE:-/etc/n0jcg/winlink-rms.env}"
POST_OFFICE_CALL="${WINLINK_POST_OFFICE_CALL:-N0JCG-11}"
RUNTIME_DIR="/var/lib/n0jcg-winlink"
SERVICE="n0jcg-winlink-rms.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIGURE_SCRIPT="${SCRIPT_DIR}/configure_winlink_rms.sh"

[[ "${EUID}" -eq 0 ]] || { echo "Run with sudo" >&2; exit 1; }
[[ "${MODE}" == "--enable" || "${MODE}" == "--disable" ]] || {
  echo "Usage: sudo $0 [--enable|--disable]" >&2
  exit 2
}
[[ -f "${ENV_FILE}" ]] || { echo "Missing ${ENV_FILE}" >&2; exit 1; }
[[ -x "${CONFIGURE_SCRIPT}" ]] || { echo "Missing ${CONFIGURE_SCRIPT}" >&2; exit 1; }

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir="/etc/n0jcg/backups/winlink-postoffice-${stamp}"
install -d -m 0700 -o root -g root "${backup_dir}"
install -m 0600 -o root -g root "${ENV_FILE}" "${backup_dir}/winlink-rms.env"
if [[ -f "${RUNTIME_DIR}/bpq32.cfg" ]]; then
  install -m 0600 -o root -g root "${RUNTIME_DIR}/bpq32.cfg" "${backup_dir}/bpq32.cfg"
fi
if [[ -f "${RUNTIME_DIR}/linmail.cfg" ]]; then
  install -m 0600 -o root -g root "${RUNTIME_DIR}/linmail.cfg" "${backup_dir}/linmail.cfg"
fi

restore_previous() {
  status=$?
  trap - ERR
  echo "Post Office configuration failed; restoring ${backup_dir}" >&2
  install -m 0600 -o root -g root "${backup_dir}/winlink-rms.env" "${ENV_FILE}"
  if [[ -f "${backup_dir}/bpq32.cfg" ]]; then
    install -m 0600 -o n0jcg -g n0jcg "${backup_dir}/bpq32.cfg" "${RUNTIME_DIR}/bpq32.cfg"
  fi
  if [[ -f "${backup_dir}/linmail.cfg" ]]; then
    install -m 0600 -o n0jcg -g n0jcg "${backup_dir}/linmail.cfg" "${RUNTIME_DIR}/linmail.cfg"
  fi
  systemctl start "${SERVICE}" || true
  exit "${status}"
}
trap restore_previous ERR

set_env_value() {
  key="$1"
  value="$2"
  tmp="$(mktemp)"
  awk -v key="${key}" -v value="${value}" '
    BEGIN { found = 0 }
    index($0, key "=") == 1 { print key "=" value; found = 1; next }
    { print }
    END { if (!found) print key "=" value }
  ' "${ENV_FILE}" > "${tmp}"
  install -m 0600 -o root -g root "${tmp}" "${ENV_FILE}"
  rm -f "${tmp}"
}

systemctl stop "${SERVICE}"
if [[ "${MODE}" == "--enable" ]]; then
  set_env_value WINLINK_POST_OFFICE_ENABLED 1
  set_env_value WINLINK_POST_OFFICE_CALL "${POST_OFFICE_CALL}"
else
  set_env_value WINLINK_POST_OFFICE_ENABLED 0
fi

"${CONFIGURE_SCRIPT}" "${ENV_FILE}"

if [[ "${MODE}" == "--enable" && ! -s "${RUNTIME_DIR}/BPQUsers.dat" ]]; then
  runuser -u n0jcg -- bash -c \
    "cd '${RUNTIME_DIR}' && /opt/n0jcg/linbpq/linbpq --adduser RMS '' TRUE"
fi

systemctl start "${SERVICE}"
for _ in {1..20}; do
  systemctl is-active --quiet "${SERVICE}" || { sleep 0.5; continue; }
  if [[ "${MODE}" == "--disable" ]] || ss -ltn | grep -q ':8772 '; then
    break
  fi
  sleep 0.5
done
systemctl is-active --quiet "${SERVICE}"

if [[ "${MODE}" == "--enable" ]]; then
  ss -ltn | grep -q ':8772 '
  echo "PASS Winlink Post Office active on TCP port 8772"
else
  if ss -ltn | grep -q ':8772 '; then
    echo "Post Office listener remains active after disable" >&2
    exit 1
  fi
  echo "PASS Winlink Post Office disabled; retained mail data was not deleted"
fi
echo "Rollback backup: ${backup_dir}"
