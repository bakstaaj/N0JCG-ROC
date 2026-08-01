#!/usr/bin/env bash
set -euo pipefail

echo '=== identity and groups ==='
id
getent group dialout || true

echo '=== serial devices ==='
serial_found=0
while IFS= read -r device; do
  serial_found=1
  ls -l "${device}"
  fuser -v "${device}" 2>&1 || true
  lsof "${device}" 2>&1 || true
  udevadm info --query=property --name="${device}" 2>/dev/null \
    | grep -E '^(ID_VENDOR|ID_MODEL|ID_SERIAL|ID_PATH|DEVLINKS)=' || true
done < <(find /dev/serial/by-id /dev -maxdepth 1 \( -type l -o -type c \) 2>/dev/null \
  | grep -E '^/dev/(serial/by-id/|tty(USB|ACM)[0-9]+$)' | sort -u)
(( serial_found == 1 )) || echo 'No serial devices detected'

echo '=== ALSA capture devices ==='
arecord -l
for device in /dev/snd/*; do
  [[ -e "${device}" ]] || continue
  ls -l "${device}"
  fuser -v "${device}" 2>&1 || true
done

echo '=== active radio ownership ==='
if pgrep -a -f '(^|/)(direwolf|soundmodem|ax25d)( |$)' 2>/dev/null; then
  echo 'FAIL radio modem process is active'
  exit 1
else
  echo 'PASS no Direwolf, Soundmodem, or ax25d process is active'
fi

echo '=== ALSA capture endpoint names ==='
arecord -L | sed -n '1,80p'

echo 'FINAL: PASS'
