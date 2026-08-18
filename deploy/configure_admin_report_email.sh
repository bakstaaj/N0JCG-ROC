#!/usr/bin/env bash
set -euo pipefail

MODE=install
if [[ "${1:-}" == '--check-only' ]]; then
  MODE=check
elif [[ $# -ne 0 ]]; then
  echo 'Usage: configure_admin_report_email.sh [--check-only]'
  exit 2
fi

[[ "$(id -u)" -eq 0 ]] || { echo 'FINAL: FAIL - run with sudo'; exit 1; }
command -v python3 >/dev/null || { echo 'FINAL: FAIL - python3 is required'; exit 1; }
[[ -f /home/n0jcg/sdrdev/N0JCG-ROC/deploy/n0jcg-admin-report.service ]] || {
  echo 'FINAL: FAIL - deploy the N0JCG-ROC source first'
  exit 1
}

if [[ "${MODE}" == check ]]; then
  if [[ -s /etc/n0jcg/admin-report.env ]]; then
    echo 'FINAL: PASS - Cloudflare Email Sending credentials are installed'
  else
    echo 'FINAL: PASS - installer prerequisites are ready; credentials are not installed'
  fi
  exit 0
fi

account_id="${CLOUDFLARE_ACCOUNT_ID:-}"
api_token="${CLOUDFLARE_API_TOKEN:-}"
if [[ -z "${account_id}" ]]; then
  read -r -p 'Cloudflare account ID: ' account_id
fi
if [[ -z "${api_token}" ]]; then
  read -r -s -p 'Cloudflare Email Sending API token: ' api_token
  printf '\n'
fi
[[ "${account_id}" =~ ^[A-Za-z0-9_-]{8,128}$ ]] || { echo 'FINAL: FAIL - invalid Cloudflare account ID format'; exit 1; }
[[ ${#api_token} -ge 20 && ${#api_token} -le 512 && "${api_token}" != *[[:space:]]* ]] || {
  echo 'FINAL: FAIL - invalid Cloudflare API token format'
  exit 1
}

install -d -m 0755 /etc/n0jcg
temporary="$(mktemp /etc/n0jcg/.admin-report.env.XXXXXX)"
trap 'rm -f "${temporary}"' EXIT
chmod 0600 "${temporary}"
printf 'CLOUDFLARE_ACCOUNT_ID=%s\nCLOUDFLARE_API_TOKEN=%s\n' "${account_id}" "${api_token}" >"${temporary}"
chown root:root "${temporary}"
mv -f "${temporary}" /etc/n0jcg/admin-report.env
trap - EXIT

install -d -o n0jcg -g n0jcg -m 0750 /var/lib/n0jcg-roc
install -o n0jcg -g n0jcg -m 0640 /dev/null /var/lib/n0jcg-roc/admin-report-credentials-ready

install -m 0644 \
  /home/n0jcg/sdrdev/N0JCG-ROC/deploy/n0jcg-admin-report.service \
  /etc/systemd/system/n0jcg-admin-report.service
systemctl daemon-reload
systemctl enable --now n0jcg-admin-report.service
systemctl restart n0jcg-admin-report.service
systemctl is-active --quiet n0jcg-admin-report.service
echo 'FINAL: PASS - administrator report credentials installed; sender is ROC@n0jcg.com'
