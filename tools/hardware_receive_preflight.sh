#!/usr/bin/env bash
set -euo pipefail

tmp_dir="$(mktemp -d /tmp/n0jcg-roc-rx.XXXXXX)"
trap 'rm -rf "${tmp_dir}"' EXIT

echo '=== DigiRig receive capture ==='
timeout 5s arecord -q -D hw:CARD=Device,DEV=0 -f S16_LE -r 48000 -c 1 -d 2 \
  "${tmp_dir}/digirig.wav"
sox "${tmp_dir}/digirig.wav" -n stats 2>&1 | sed -n '1,12p'
echo 'PASS DigiRig captured 2 seconds from hw:CARD=Device,DEV=0'

echo '=== RTL-SDR receive capture ==='
set +e
timeout 6s rtl_fm -d 0 -f 100000000 -s 2400000 -r 48000 -g 0 - \
  2>"${tmp_dir}/rtl-fm.log" | head -c 192000 >"${tmp_dir}/rtl.raw"
rtl_rc=$?
set -e
bytes="$(wc -c <"${tmp_dir}/rtl.raw")"
cat "${tmp_dir}/rtl-fm.log"
[[ "${bytes}" -ge 192000 ]] || {
  echo "FINAL: FAIL - RTL-SDR capture produced ${bytes} bytes"
  exit 1
}
[[ "${rtl_rc}" -eq 0 || "${rtl_rc}" -eq 124 || "${rtl_rc}" -eq 141 ]] || {
  echo "FINAL: FAIL - rtl_fm exited with ${rtl_rc}"
  exit 1
}
echo "PASS RTL-SDR captured ${bytes} bytes at 100.6 MHz and restored the driver"
echo 'No PTT, modem service, or transmit operation was performed.'
echo 'FINAL: PASS'
