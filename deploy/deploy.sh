#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ROC_HOST="${ROC_HOST:-192.168.68.114}"
ROC_USER="${ROC_USER:-n0jcg}"
ROC_PORT="${ROC_PORT:-80}"
ROC_REMOTE_DIR="${ROC_REMOTE_DIR:-/home/n0jcg/sdrdev/N0JCG-ROC}"
ROC_IDENTITY_FILE="${ROC_IDENTITY_FILE:-${HOME}/.ssh/n0jcg_roc_ed25519}"
MODE=deploy
if [[ -n "${SUDO_USER:-}" || "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo 'FINAL: FAIL - run deploy.sh as the development user, not with sudo'
  exit 1
fi
if [[ "${1:-}" == '--check-only' ]]; then MODE=check; elif [[ $# -ne 0 ]]; then echo 'Usage: deploy.sh [--check-only]'; exit 2; fi
[[ "${ROC_PORT}" =~ ^[0-9]+$ ]] && (( ROC_PORT >= 1 && ROC_PORT <= 65535 )) || { echo 'FINAL: FAIL - invalid ROC_PORT'; exit 1; }
[[ "${ROC_REMOTE_DIR}" == '/home/n0jcg/sdrdev/N0JCG-ROC' ]] || { echo 'FINAL: FAIL - unexpected ROC_REMOTE_DIR'; exit 1; }
for required in README.md web/index.html web/styles.css web/app.js deploy/n0jcg-roc.service deploy/n0jcg-admin-report.service deploy/n0jcg-aprs-rx.service deploy/n0jcg-aprs-monitor.service deploy/n0jcg-weather.service deploy/n0jcg-cwop-weather.service deploy/n0jcg-operator-helper.service deploy/n0jcg-winlink-rms.service deploy/n0jcg-winlink-watchdog.service deploy/n0jcg-vara-fm.service deploy/run-vara-fm.sh deploy/operator_helper.py src/n0jcg_roc/operator_activity.py deploy/configure_operator_controls.sh deploy/configure_admin_report_email.sh tools/validate.sh tools/aprs_config_backup.py tools/cwop_weather_uploader.py tools/winlink_protocol_watchdog.py tools/capture_winlink_kiss.sh; do
  [[ -f "${PROJECT_DIR}/${required}" ]] || { echo "FINAL: FAIL - missing ${required}"; exit 1; }
done
[[ -f "${ROC_IDENTITY_FILE}" ]] || { echo 'FINAL: FAIL - run deploy/setup_server_auth.sh first'; exit 1; }
make -C "${PROJECT_DIR}" test
SSH=(ssh -i "${ROC_IDENTITY_FILE}" -o BatchMode=yes -o ConnectTimeout=8)
RSYNC_SSH="ssh -i ${ROC_IDENTITY_FILE} -o BatchMode=yes -o ConnectTimeout=8"
"${SSH[@]}" "${ROC_USER}@${ROC_HOST}" "test \"\$(id -un)\" = n0jcg && command -v python3 && command -v systemctl"
listener="$(${SSH[@]} "${ROC_USER}@${ROC_HOST}" "ss -ltnH 'sport = :${ROC_PORT}' || true")"
if [[ -n "${listener}" ]]; then "${SSH[@]}" "${ROC_USER}@${ROC_HOST}" 'systemctl is-active --quiet n0jcg-roc.service' || { echo "FINAL: FAIL - port ${ROC_PORT} is owned by an unknown listener"; exit 1; }; fi
if [[ "${MODE}" == check ]]; then echo 'FINAL: PASS - deployment preflight only; no files changed'; exit 0; fi
[[ -n "${ROC_SUDO_PASS:-}" ]] || { echo 'FINAL: FAIL - set ROC_SUDO_PASS transiently for service restart'; exit 1; }
if ! printf '%s\n' "${ROC_SUDO_PASS}" | "${SSH[@]}" "${ROC_USER}@${ROC_HOST}" 'sudo -S -p "" -k true' >/dev/null 2>&1; then
  echo 'FINAL: FAIL - ROC_SUDO_PASS was rejected; no files were deployed'
  exit 1
fi
stage_dir="$(mktemp -d)"; trap 'rm -rf "${stage_dir}"' EXIT
rsync -a --exclude=.git --exclude=.server.env --exclude=config/station.toml --exclude=__pycache__ --exclude=runtime "${PROJECT_DIR}/" "${stage_dir}/"
# The remote tree may contain root-owned service artifacts from an earlier
# install. Transfer content and timestamps, but never require the SSH user to
# preserve permissions, owner, or group metadata on existing files.
rsync -rltz --no-perms --no-owner --no-group --delete --exclude=config/station.toml --exclude=runtime -e "${RSYNC_SSH}" "${stage_dir}/" "${ROC_USER}@${ROC_HOST}:${ROC_REMOTE_DIR}/"
"${SSH[@]}" "${ROC_USER}@${ROC_HOST}" "cd ${ROC_REMOTE_DIR} && if [ ! -f config/station.toml ]; then cp config/station.example.toml config/station.toml; fi && chmod +x tools/*.sh deploy/*.sh && ./tools/validate.sh"
printf '%s\n' "${ROC_SUDO_PASS}" | "${SSH[@]}" "${ROC_USER}@${ROC_HOST}" "sudo -S -p '' sh -c 'install -d -m 0755 /usr/local/libexec/n0jcg && install -m 0644 ${ROC_REMOTE_DIR}/src/n0jcg_roc/operator_activity.py /usr/local/libexec/n0jcg/operator_activity.py && install -m 0755 ${ROC_REMOTE_DIR}/deploy/operator_helper.py /usr/local/libexec/n0jcg/operator_helper.py && install -m 0755 ${ROC_REMOTE_DIR}/deploy/run-vara-fm.sh /usr/local/libexec/n0jcg/run-vara-fm.sh && install -m 0644 ${ROC_REMOTE_DIR}/deploy/n0jcg-operator-helper.service /etc/systemd/system/n0jcg-operator-helper.service && install -m 0644 ${ROC_REMOTE_DIR}/deploy/n0jcg-vara-fm.service /etc/systemd/system/n0jcg-vara-fm.service && install -m 0644 ${ROC_REMOTE_DIR}/deploy/n0jcg-winlink-watchdog.service /etc/systemd/system/n0jcg-winlink-watchdog.service && systemctl daemon-reload && systemctl enable n0jcg-operator-helper.service n0jcg-vara-fm.service n0jcg-winlink-watchdog.service && systemctl restart n0jcg-operator-helper.service n0jcg-vara-fm.service n0jcg-winlink-watchdog.service'"
printf '%s\n' "${ROC_SUDO_PASS}" | "${SSH[@]}" "${ROC_USER}@${ROC_HOST}" "sudo -S -p '' sh -c 'install -d -o n0jcg -g n0jcg -m 0755 /var/lib/n0jcg-roc && chown n0jcg:n0jcg /var/lib/n0jcg-roc && if [ -e /var/lib/n0jcg-roc/cwop.json ]; then chown n0jcg:n0jcg /var/lib/n0jcg-roc/cwop.json; fi && install -m 0644 ${ROC_REMOTE_DIR}/deploy/n0jcg-roc.service /etc/systemd/system/n0jcg-roc.service && systemctl daemon-reload && systemctl enable n0jcg-roc.service && systemctl restart n0jcg-roc.service'"
printf '%s\n' "${ROC_SUDO_PASS}" | "${SSH[@]}" "${ROC_USER}@${ROC_HOST}" "sudo -S -p '' sh -c 'install -m 0644 ${ROC_REMOTE_DIR}/deploy/n0jcg-aprs-rx.service /etc/systemd/system/n0jcg-aprs-rx.service && install -m 0644 ${ROC_REMOTE_DIR}/deploy/n0jcg-aprs-monitor.service /etc/systemd/system/n0jcg-aprs-monitor.service && systemctl daemon-reload && systemctl enable n0jcg-aprs-rx.service n0jcg-aprs-monitor.service && systemctl restart n0jcg-aprs-rx.service n0jcg-aprs-monitor.service'"
printf '%s\n' "${ROC_SUDO_PASS}" | "${SSH[@]}" "${ROC_USER}@${ROC_HOST}" "sudo -S -p '' sh -c 'install -m 0644 ${ROC_REMOTE_DIR}/deploy/n0jcg-weather.service /etc/systemd/system/n0jcg-weather.service && systemctl daemon-reload && systemctl enable n0jcg-weather.service && systemctl restart n0jcg-weather.service'"
printf '%s\n' "${ROC_SUDO_PASS}" | "${SSH[@]}" "${ROC_USER}@${ROC_HOST}" "sudo -S -p '' sh -c 'install -m 0644 ${ROC_REMOTE_DIR}/deploy/n0jcg-cwop-weather.service /etc/systemd/system/n0jcg-cwop-weather.service && install -m 0755 ${ROC_REMOTE_DIR}/tools/cwop_weather_uploader.py /usr/local/libexec/n0jcg-cwop-weather.py && systemctl daemon-reload && systemctl enable n0jcg-cwop-weather.service && systemctl restart n0jcg-cwop-weather.service'"
printf '%s\n' "${ROC_SUDO_PASS}" | "${SSH[@]}" "${ROC_USER}@${ROC_HOST}" "sudo -S -p '' sh -c 'install -m 0644 ${ROC_REMOTE_DIR}/deploy/n0jcg-admin-report.service /etc/systemd/system/n0jcg-admin-report.service && systemctl daemon-reload && systemctl enable n0jcg-admin-report.service && systemctl restart n0jcg-admin-report.service'"
"${SSH[@]}" "${ROC_USER}@${ROC_HOST}" "systemctl is-enabled --quiet n0jcg-roc.service && systemctl is-active --quiet n0jcg-roc.service && systemctl is-active --quiet n0jcg-operator-helper.service && systemctl is-active --quiet n0jcg-admin-report.service && curl -fsS http://127.0.0.1:${ROC_PORT}/api/health"
curl -fsS "http://${ROC_HOST}:${ROC_PORT}/" | grep -F 'Radio Operations Center' >/dev/null
curl -fsS "http://${ROC_HOST}:${ROC_PORT}/app.js" | grep -F '/api/health' >/dev/null
curl -fsS "http://${ROC_HOST}:${ROC_PORT}/api/health" | grep -F '"transmit"' >/dev/null
curl -fsS "http://${ROC_HOST}:${ROC_PORT}/api/operator/status" | grep -F '"controls"' >/dev/null
echo 'FINAL: PASS'
