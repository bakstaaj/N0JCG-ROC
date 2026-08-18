#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ROC_HOST="${ROC_HOST:-192.168.68.114}"
ROC_USER="${ROC_USER:-n0jcg}"
ROC_PORT="${ROC_PORT:-80}"
ROC_IDENTITY_FILE="${ROC_IDENTITY_FILE:-${HOME}/.ssh/n0jcg_roc_ed25519}"
BASE_URL="http://${ROC_HOST}:${ROC_PORT}"
ROC_EXPECT_HARDWARE_STATE="${ROC_EXPECT_HARDWARE_STATE:-}"
ROC_EXPECT_RTL_COUNT="${ROC_EXPECT_RTL_COUNT:-}"

[[ "${ROC_PORT}" =~ ^[0-9]+$ ]] && (( ROC_PORT >= 1 && ROC_PORT <= 65535 )) || {
  echo 'FINAL: FAIL - invalid ROC_PORT'
  exit 1
}
[[ -f "${ROC_IDENTITY_FILE}" ]] || { echo 'FINAL: FAIL - deployment SSH key missing'; exit 1; }

local_js_hash="$(sha256sum "${PROJECT_DIR}/web/app.js" | awk '{print $1}')"
served_js_hash="$(curl -fsS "${BASE_URL}/app.js" | sha256sum | awk '{print $1}')"
local_index_hash="$(sha256sum "${PROJECT_DIR}/web/index.html" | awk '{print $1}')"
served_index_hash="$(curl -fsS "${BASE_URL}/" | sha256sum | awk '{print $1}')"

[[ "${local_js_hash}" == "${served_js_hash}" ]] || { echo 'FINAL: FAIL - served app.js differs from source'; exit 1; }
[[ "${local_index_hash}" == "${served_index_hash}" ]] || { echo 'FINAL: FAIL - served index.html differs from source'; exit 1; }
echo 'PASS served app.js and index.html exactly match local source'

health_json="$(curl -fsS "${BASE_URL}/api/health")"
system_json="$(curl -fsS "${BASE_URL}/api/system")"
ROC_EXPECT_HARDWARE_STATE="${ROC_EXPECT_HARDWARE_STATE}" ROC_EXPECT_RTL_COUNT="${ROC_EXPECT_RTL_COUNT}" python3 - "${health_json}" "${system_json}" <<'PY'
import json
import os
import sys

health = json.loads(sys.argv[1])
system = json.loads(sys.argv[2])
assert health["status"] == "ok", health
assert isinstance(health["transmit"]["ready"], bool), health
assert isinstance(health["transmit"]["reasons"], list), health
assert system["host"]["hostname"] == "n0jcg-roc", system
assert system["tooling"]["ready"] is True, system
expected_rtl = os.environ.get("ROC_EXPECT_RTL_COUNT", "")
if expected_rtl:
    assert system["hardware"]["rtl_sdr_count"] == int(expected_rtl), system
expected = os.environ.get("ROC_EXPECT_HARDWARE_STATE", "")
if expected:
    assert system["hardware"]["state"] == expected, system
PY
echo "PASS live APIs report ready tooling, ${ROC_EXPECT_HARDWARE_STATE:-observed} hardware, and a valid transmit-interlock state"

ssh -i "${ROC_IDENTITY_FILE}" -o BatchMode=yes -o ConnectTimeout=8 \
  "${ROC_USER}@${ROC_HOST}" \
  'systemctl is-enabled --quiet n0jcg-roc.service n0jcg-weather.service n0jcg-admin-report.service && systemctl is-active --quiet n0jcg-roc.service n0jcg-weather.service n0jcg-admin-report.service && test -z "$(systemctl --failed --no-legend --plain)"'
echo 'PASS ROC, weather, and administrator report systemd services enabled/active with zero failed units'
echo 'FINAL: PASS'
