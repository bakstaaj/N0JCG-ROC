#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ROC_HOST="${ROC_HOST:-192.168.68.145}"
ROC_USER="${ROC_USER:-n0jcg}"
ROC_PORT="${ROC_PORT:-8095}"
ROC_REMOTE_DIR="${ROC_REMOTE_DIR:-/home/n0jcg/sdrdev/N0JCG-ROC}"
ROC_IDENTITY_FILE="${ROC_IDENTITY_FILE:-${HOME}/.ssh/n0jcg_roc_ed25519}"
MODE=deploy

if [[ "${1:-}" == '--check-only' ]]; then
  MODE=check
elif [[ $# -ne 0 ]]; then
  echo 'Usage: deploy.sh [--check-only]'
  exit 2
fi

[[ "${ROC_PORT}" =~ ^[0-9]+$ ]] && (( ROC_PORT >= 1 && ROC_PORT <= 65535 )) || {
  echo 'FINAL: FAIL - invalid ROC_PORT'
  exit 1
}
[[ "${ROC_REMOTE_DIR}" == '/home/n0jcg/sdrdev/N0JCG-ROC' ]] || {
  echo 'FINAL: FAIL - unexpected ROC_REMOTE_DIR'
  exit 1
}

for required in README.md web/index.html web/styles.css web/app.js deploy/n0jcg-roc.service tools/validate.sh; do
  [[ -f "${PROJECT_DIR}/${required}" ]] || { echo "FINAL: FAIL - missing ${required}"; exit 1; }
done
[[ -f "${ROC_IDENTITY_FILE}" ]] || { echo 'FINAL: FAIL - run deploy/setup_server_auth.sh first'; exit 1; }

make -C "${PROJECT_DIR}" test

SSH=(ssh -i "${ROC_IDENTITY_FILE}" -o BatchMode=yes -o ConnectTimeout=8)
RSYNC_SSH="ssh -i ${ROC_IDENTITY_FILE} -o BatchMode=yes -o ConnectTimeout=8"
"${SSH[@]}" "${ROC_USER}@${ROC_HOST}" "test \"\$(id -un)\" = n0jcg && command -v python3 && command -v systemctl"

listener="$(${SSH[@]} "${ROC_USER}@${ROC_HOST}" "ss -ltnH 'sport = :${ROC_PORT}' || true")"
if [[ -n "${listener}" ]]; then
  "${SSH[@]}" "${ROC_USER}@${ROC_HOST}" 'systemctl is-active --quiet n0jcg-roc.service' || {
    echo "FINAL: FAIL - port ${ROC_PORT} is owned by an unknown listener"
    exit 1
  }
fi

if [[ "${MODE}" == check ]]; then
  echo 'FINAL: PASS - deployment preflight only; no files changed'
  exit 0
fi

[[ -n "${ROC_SUDO_PASS:-}" ]] || { echo 'FINAL: FAIL - set ROC_SUDO_PASS transiently for service restart'; exit 1; }
stage_dir="$(mktemp -d)"
trap 'rm -rf "${stage_dir}"' EXIT
rsync -a --exclude=.git --exclude=.server.env --exclude=config/station.toml --exclude=__pycache__ --exclude=runtime "${PROJECT_DIR}/" "${stage_dir}/"

rsync -az --delete \
  --exclude=config/station.toml \
  --exclude=runtime \
  -e "${RSYNC_SSH}" \
  "${stage_dir}/" "${ROC_USER}@${ROC_HOST}:${ROC_REMOTE_DIR}/"

"${SSH[@]}" "${ROC_USER}@${ROC_HOST}" "cd ${ROC_REMOTE_DIR} && if [ ! -f config/station.toml ]; then cp config/station.example.toml config/station.toml; fi && chmod +x tools/*.sh deploy/*.sh && ./tools/validate.sh"
printf '%s\n' "${ROC_SUDO_PASS}" | "${SSH[@]}" "${ROC_USER}@${ROC_HOST}" "sudo -S -p '' systemctl restart n0jcg-roc.service"
"${SSH[@]}" "${ROC_USER}@${ROC_HOST}" "systemctl is-enabled --quiet n0jcg-roc.service && systemctl is-active --quiet n0jcg-roc.service && curl -fsS http://127.0.0.1:${ROC_PORT}/api/health"

curl -fsS "http://${ROC_HOST}:${ROC_PORT}/" | grep -Fq 'Radio Operations Center'
curl -fsS "http://${ROC_HOST}:${ROC_PORT}/app.js" | grep -Fq '/api/health'
curl -fsS "http://${ROC_HOST}:${ROC_PORT}/api/health" | grep -Fq '"ready": false'
echo 'FINAL: PASS'
