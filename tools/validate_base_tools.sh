#!/usr/bin/env bash
set -euo pipefail

required_commands=(
  aplay arecord axcall curl direwolf git jq lsof make python3
  rsync rtl_eeprom rtl_test socat sox
)
failures=0

for command_name in "${required_commands[@]}"; do
  if command -v "${command_name}" >/dev/null 2>&1; then
    printf 'PASS command %-12s %s\n' "${command_name}" "$(command -v "${command_name}")"
  else
    printf 'FAIL command %-12s missing\n' "${command_name}"
    failures=$((failures + 1))
  fi
done

if systemctl is-active --quiet direwolf.service 2>/dev/null; then
  echo 'FAIL direwolf.service is unexpectedly active'
  failures=$((failures + 1))
else
  echo 'PASS no Direwolf service is active'
fi

if [[ -e /dev/serial/by-id ]] || lsusb | grep -Eqi 'RTL|CP210|DigiRig'; then
  echo 'INFO radio-related hardware is present; run the hardware ownership inventory'
else
  echo 'PASS bare-server state retained; no radio USB hardware detected'
fi

if [[ -n "$(systemctl --failed --no-legend --plain)" ]]; then
  echo 'FAIL systemd reports failed units'
  systemctl --failed --no-pager
  failures=$((failures + 1))
else
  echo 'PASS zero failed systemd units'
fi

python3 - <<'PY'
import json
from urllib.request import urlopen

with urlopen("http://127.0.0.1:8095/api/health", timeout=5) as response:
    health = json.load(response)
assert health["status"] == "ok", health
assert health["transmit"]["ready"] is False, health
print("PASS ROC health API online with transmit locked")
PY

(( failures == 0 )) || { echo "FINAL: FAIL - ${failures} checks failed"; exit 1; }
echo 'FINAL: PASS'
