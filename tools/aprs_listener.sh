#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_dir="${project_dir}/runtime/aprs"
rtl_gain_db="${RTL_GAIN_DB:-0}"
rtl_serial="${APRS_RTL_SERIAL:-00014439}"
audio_capture_enabled="${APRS_AUDIO_CAPTURE:-0}"
audio_capture_seconds="${APRS_AUDIO_CAPTURE_SECONDS:-60}"
igate_enabled="${APRS_IGATE_ENABLED:-0}"
igate_server="${APRS_IGATE_SERVER:-rotate.aprs2.net}"
igate_port="${APRS_IGATE_PORT:-14580}"
igate_login="${APRS_IGATE_LOGIN:-}"
igate_passcode="${APRS_IGATE_PASSCODE:-}"
igate_beacon_enabled="${APRS_IGATE_BEACON_ENABLED:-1}"
igate_beacon_interval="${APRS_IGATE_BEACON_INTERVAL:-720:00}"
igate_beacon_comment="${APRS_IGATE_BEACON_COMMENT:-N0JCG ROC RX-only iGate 144.390 MHz}"
# Use the nominal APRS channel and enable the RTL FM demodulator's DC blocker.
# Offset tuning is not supported reliably by this tuner and only adds a warning.
# This rtl_fm build reports an internal +252 kHz tuning offset in this 48 kHz
# DC-blocker mode. Request 144.138 MHz so the effective APRS channel is 144.390.
rtl_frequency_hz="${APRS_RTL_FREQUENCY_HZ:-144138000}"
mkdir -p "${runtime_dir}"
direwolf_config="${runtime_dir}/direwolf.conf"
cp "${project_dir}/config/direwolf.aprs-rx.example.conf" "${direwolf_config}"
if [[ "${igate_enabled}" == "1" ]]; then
  [[ -n "${igate_login}" && -n "${igate_passcode}" ]] || {
    echo "APRS iGate enabled but APRS_IGATE_LOGIN/APRS_IGATE_PASSCODE is incomplete" >&2
    exit 2
  }
  {
    printf '\n# Optional receive-only RF-to-APRS-IS iGate\n'
    printf 'IGSERVER %s %s\n' "${igate_server}" "${igate_port}"
    printf 'IGLOGIN %s %s\n' "${igate_login}" "${igate_passcode}"
  } >>"${direwolf_config}"
  if [[ "${igate_beacon_enabled}" == "1" ]]; then
    read -r beacon_latitude beacon_longitude < <(python3 - "${project_dir}/config/station.toml" <<'PY'
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
sys.path.insert(0, str(config_path.parents[1] / "src"))
from n0jcg_roc.config import load_station_config

station = load_station_config(config_path)["station"]

def coordinate(value, *, latitude):
    value = float(value)
    degrees = int(abs(value))
    minutes = (abs(value) - degrees) * 60
    hemisphere = ("N" if value >= 0 else "S") if latitude else ("E" if value >= 0 else "W")
    width = 2 if latitude else 3
    return f"{degrees:0{width}d}^{minutes:07.4f}{hemisphere}"

print(coordinate(station["latitude"], latitude=True), coordinate(station["longitude"], latitude=False))
PY
)
    printf 'PBEACON SENDTO=IG DELAY=0:30 EVERY=%s SYMBOL="igate" OVERLAY=R LAT=%s LONG=%s COMMENT="%s"\n' \
      "${igate_beacon_interval}" "${beacon_latitude}" "${beacon_longitude}" "${igate_beacon_comment}" \
      >>"${direwolf_config}"
  fi
fi
if [[ "${audio_capture_enabled}" == "1" ]]; then
  exec bash -o pipefail -c 'rtl_fm -d "$7" -f "$6" -M fm -E dc -s 48000 -r 48000 -g "$3" - 2>>"$1/rtl.log" | python3 "$4" --output "$1/audio-ring.wav" --seconds "$5" --sample-rate 48000 | stdbuf -oL direwolf -q h -r 48000 -c "$2" - 2>&1 | stdbuf -oL tee -a "$1/packets.log"' _ "${runtime_dir}" "${direwolf_config}" "${rtl_gain_db}" "${project_dir}/tools/aprs_audio_capture.py" "${audio_capture_seconds}" "${rtl_frequency_hz}" "${rtl_serial}"
else
  exec bash -o pipefail -c 'rtl_fm -d "$5" -f "$4" -M fm -E dc -s 48000 -r 48000 -g "$3" - 2>>"$1/rtl.log" | stdbuf -oL direwolf -q h -r 48000 -c "$2" - 2>&1 | stdbuf -oL tee -a "$1/packets.log"' _ "${runtime_dir}" "${direwolf_config}" "${rtl_gain_db}" "${rtl_frequency_hz}" "${rtl_serial}"
fi
