#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_dir="${project_dir}/runtime/aprs"
rtl_gain_db="${RTL_GAIN_DB:-0}"
audio_capture_enabled="${APRS_AUDIO_CAPTURE:-0}"
audio_capture_seconds="${APRS_AUDIO_CAPTURE_SECONDS:-60}"
mkdir -p "${runtime_dir}"
if [[ "${audio_capture_enabled}" == "1" ]]; then
  exec bash -c 'rtl_fm -d 00000144 -f 144390000 -M fm -s 240000 -r 48000 -g "$3" - 2>>"$1/rtl.log" | python3 "$4" --output "$1/audio-ring.wav" --seconds "$5" --sample-rate 48000 | stdbuf -oL direwolf -q h -r 48000 -c "$2" - 2>&1 | stdbuf -oL tee -a "$1/packets.log"' _ "${runtime_dir}" "${project_dir}/config/direwolf.aprs-rx.example.conf" "${rtl_gain_db}" "${project_dir}/tools/aprs_audio_capture.py" "${audio_capture_seconds}"
else
  exec bash -c 'rtl_fm -d 00000144 -f 144390000 -M fm -s 240000 -r 48000 -g "$3" - 2>>"$1/rtl.log" | stdbuf -oL direwolf -q h -r 48000 -c "$2" - 2>&1 | stdbuf -oL tee -a "$1/packets.log"' _ "${runtime_dir}" "${project_dir}/config/direwolf.aprs-rx.example.conf" "${rtl_gain_db}"
fi
