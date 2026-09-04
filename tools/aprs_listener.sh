#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_dir="${project_dir}/runtime/aprs"
packet_logger="${project_dir}/tools/aprs_packet_logger.py"
rtl_gain_db="${RTL_GAIN_DB:-0}"
rtl_serial="${APRS_RTL_SERIAL:-00014439}"
audio_capture_enabled="${APRS_AUDIO_CAPTURE:-0}"
audio_capture_seconds="${APRS_AUDIO_CAPTURE_SECONDS:-60}"
audio_segment_dir="${APRS_AUDIO_SEGMENT_DIR:-}"
audio_segment_seconds="${APRS_AUDIO_SEGMENT_SECONDS:-0}"
igate_enabled="${APRS_IGATE_ENABLED:-1}"
igate_server="${APRS_IGATE_SERVER:-rotate.aprs2.net}"
igate_port="${APRS_IGATE_PORT:-14580}"
igate_login="${APRS_IGATE_LOGIN:-}"
igate_passcode="${APRS_IGATE_PASSCODE:-}"
igate_beacon_enabled="${APRS_IGATE_BEACON_ENABLED:-1}"
igate_beacon_interval="${APRS_IGATE_BEACON_INTERVAL:-30:00}"
igate_beacon_comment="${APRS_IGATE_BEACON_COMMENT:-N0JCG ROC RX-only iGate 144.390 MHz https://n0jcg.com}"
direwolf_audio_stats_seconds="${APRS_DIREWOLF_AUDIO_STATS_SECONDS:-10}"
rtl_frequency_hz="${APRS_RTL_FREQUENCY_HZ:-144390000}"
rtl_ppm="${APRS_RTL_PPM:-0}"
mkdir -p "${runtime_dir}"
direwolf_config="${runtime_dir}/direwolf.conf"
cp "${project_dir}/config/direwolf.aprs-rx.example.conf" "${direwolf_config}"
# This listener is receive-only.  Dire Wolf otherwise opens the default ALSA
# playback device even when no RF transmit control is configured, which conflicts
# with the Winlink modem's shared DigiRig audio device.
printf '\n# Receive-only: never claim a physical playback device.\nADEVICE null null\n' >>"${direwolf_config}"
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
  exec bash -o pipefail -c 'rtl_fm -d "$7" -f "$6" -M fm -E dc -p "${12}" -s 48000 -r 48000 -g "$3" - 2>>"$1/rtl.log" | python3 "$4" --output "$1/audio-ring.wav" --seconds "$5" --sample-rate 48000 ${10:+--segment-dir "${10}" --segment-seconds "${11}"} | stdbuf -oL direwolf -q h -r 48000 -a "$9" -c "$2" - 2>&1 | python3 "$8" --log "$1/packets.log" --records "$1/packet-records.jsonl"' _ "${runtime_dir}" "${direwolf_config}" "${rtl_gain_db}" "${project_dir}/tools/aprs_audio_capture.py" "${audio_capture_seconds}" "${rtl_frequency_hz}" "${rtl_serial}" "${packet_logger}" "${direwolf_audio_stats_seconds}" "${audio_segment_dir}" "${audio_segment_seconds}" "${rtl_ppm}"
else
  exec bash -o pipefail -c 'rtl_fm -d "$5" -f "$4" -M fm -E dc -p "${8}" -s 48000 -r 48000 -g "$3" - 2>>"$1/rtl.log" | stdbuf -oL direwolf -q h -r 48000 -a "$7" -c "$2" - 2>&1 | python3 "$6" --log "$1/packets.log" --records "$1/packet-records.jsonl"' _ "${runtime_dir}" "${direwolf_config}" "${rtl_gain_db}" "${rtl_frequency_hz}" "${rtl_serial}" "${packet_logger}" "${direwolf_audio_stats_seconds}" "${rtl_ppm}"
fi
