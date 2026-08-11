#!/usr/bin/env bash
set -euo pipefail

SESSION_KEY="${1:-}"
ENV_FILE="${WINLINK_ENV_FILE:-/etc/n0jcg/winlink-rms.env}"
BASE_URL="http://127.0.0.1:8088/Mail"

[[ "${EUID}" -eq 0 ]] || { echo "Run with sudo" >&2; exit 1; }
[[ "${SESSION_KEY}" =~ ^M[0-9A-F]+$ ]] || {
  echo "Pass the active loopback Mail Management session key" >&2
  exit 2
}
[[ -f "${ENV_FILE}" ]] || { echo "Missing ${ENV_FILE}" >&2; exit 1; }

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a
[[ -n "${WINLINK_BASE_CALL:-}" ]] || { echo "Missing WINLINK_BASE_CALL" >&2; exit 1; }
[[ -n "${WINLINK_CMS_PASSWORD:-}" ]] || { echo "Missing WINLINK_CMS_PASSWORD" >&2; exit 1; }
[[ -n "${WINLINK_OPERATOR_NAME:-}" ]] || { echo "Missing WINLINK_OPERATOR_NAME" >&2; exit 1; }
[[ "${WINLINK_OPERATOR_NAME}" != *"|"* ]] || {
  echo "WINLINK_OPERATOR_NAME cannot contain a pipe character" >&2
  exit 2
}

# Select the user in the active BPQMail management session, then send the raw
# pipe-delimited format used by LinBPQ. The CMS password travels in the request
# body on ROC loopback and is never placed in argv or printed.
curl --fail --silent --show-error \
  --data-binary "${WINLINK_BASE_CALL}" \
  "${BASE_URL}/UserDetails?${SESSION_KEY}" >/dev/null

{
  printf 'false|true|false|true|true|true|false|||||'
  printf 'false|false|false|false|false|false|false|false||0|'
  printf '%s' "${WINLINK_OPERATOR_NAME}"
  printf '||'
  printf '%s' "${WINLINK_CMS_PASSWORD}"
  printf '||||'
} | curl --fail --silent --show-error \
  --data-binary @- \
  "${BASE_URL}/UserSave?${SESSION_KEY}" >/dev/null

echo "PASS N0JCG BPQMail user profile configured for Winlink Express and CMS polling"
