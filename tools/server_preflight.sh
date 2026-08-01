#!/usr/bin/env bash
set -euo pipefail

failures=0

check_command() {
  local command_name="$1"
  if command -v "${command_name}" >/dev/null 2>&1; then
    printf 'PASS command %-12s %s\n' "${command_name}" "$(command -v "${command_name}")"
  else
    printf 'INFO command %-12s not installed\n' "${command_name}"
  fi
}

printf 'HOSTNAME=%s\n' "$(hostname)"
printf 'KERNEL=%s\n' "$(uname -r)"
printf 'USER=%s\n' "$(id -un)"

if [[ "$(id -un)" == "n0jcg" ]]; then
  echo 'PASS operator account is n0jcg'
else
  echo 'FAIL operator account is not n0jcg'
  failures=$((failures + 1))
fi

if [[ -r /etc/os-release ]]; then
  . /etc/os-release
  printf 'OS=%s\n' "${PRETTY_NAME}"
fi

check_command python3
check_command arecord
check_command aplay
check_command rtl_test
check_command rtl_eeprom
check_command direwolf

echo 'USB_DEVICES_BEGIN'
lsusb 2>&1 || true
echo 'USB_DEVICES_END'

echo 'SERIAL_BY_ID_BEGIN'
find /dev/serial/by-id -maxdepth 1 -type l -printf '%f -> %l\n' 2>/dev/null || true
echo 'SERIAL_BY_ID_END'

echo 'ALSA_CAPTURE_BEGIN'
arecord -l 2>&1 || true
echo 'ALSA_CAPTURE_END'

echo 'RTL_EEPROM_BEGIN'
if command -v rtl_eeprom >/dev/null 2>&1; then
  rtl_eeprom 2>&1 || true
else
  echo 'rtl_eeprom not installed'
fi
echo 'RTL_EEPROM_END'

if (( failures > 0 )); then
  echo "FINAL: FAIL (${failures} required checks failed)"
  exit 1
fi

echo 'FINAL: PASS'
