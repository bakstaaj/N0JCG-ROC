#!/usr/bin/env bash
set -euo pipefail

[[ "${EUID}" -eq 0 ]] || { echo "Run with sudo" >&2; exit 1; }
[[ "${1:-}" == "--confirm-dummy-load" ]] || {
  echo "Refusing test without --confirm-dummy-load" >&2
  exit 2
}

frequency_hz="${WINLINK_TEST_FREQUENCY_HZ:-145070000}"
rtl_request_hz="$((frequency_hz - 252000))"
rtl_serial="${APRS_RTL_SERIAL:-00014439}"
rtl_gain_db="${WINLINK_TEST_RTL_GAIN_DB:-10}"
capture_path="${WINLINK_TEST_CAPTURE_PATH:-/tmp/winlink-dummyload.wav}"
frame="N0JCG-10>APDW17:Winlink RMS dummy-load RF test"
aprs_was_active=0

if systemctl is-active --quiet n0jcg-aprs-rx.service; then
  aprs_was_active=1
  systemctl stop n0jcg-aprs-rx.service
fi
restore_aprs() {
  if [[ "${aprs_was_active}" == "1" ]]; then
    systemctl start n0jcg-aprs-rx.service || true
  fi
}
trap restore_aprs EXIT

systemctl is-active --quiet n0jcg-winlink-modem.service || {
  echo "Winlink modem service is not active" >&2
  exit 1
}
grep -q '^PTT ' /etc/n0jcg/winlink-direwolf.conf || {
  echo "Winlink PTT is not configured" >&2
  exit 1
}

rm -f -- "${capture_path}"
rtl_fm -d "${rtl_serial}" -f "${rtl_request_hz}" -M fm -E dc \
  -s 48000 -r 48000 -g "${rtl_gain_db}" - 2>/tmp/winlink-rtl.log \
  | sox -t raw -r 48000 -e signed-integer -b 16 -c 1 - \
      "${capture_path}" trim 0 8 &
capture_pid=$!
sleep 2
printf '%s\n' "${frame}" | timeout 5 kissutil -h 127.0.0.1 -p 8010
wait "${capture_pid}"

echo "CAPTURE ${capture_path}"
sox "${capture_path}" -n stat 2>&1 | grep -E 'Samples read|Length \(seconds\)|Maximum amplitude|RMS.*amplitude'
echo "DECODE"
atest -B 1200 "${capture_path}" 2>&1 | sed -n '/N0JCG-10>/p;/packets decoded in/p'
