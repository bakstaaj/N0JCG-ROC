#!/usr/bin/env bash
set -euo pipefail

# Collect a bounded, timestamped APRS receive session.  This never enables
# transmit; it only observes the existing receive-only listener.
runtime_dir="${APRS_RUNTIME_DIR:-/home/n0jcg/sdrdev/N0JCG-ROC/runtime/aprs}"
session_root="${APRS_DRIVE_SESSION_ROOT:-/var/lib/n0jcg-roc/aprs-drive-tests}"
state_file="/run/n0jcg-aprs-drive-test"
service="n0jcg-aprs-rx.service"
dropin_dir="/etc/systemd/system/${service}.d"
dropin_file="${dropin_dir}/drive-capture.conf"
segment_dir="${runtime_dir}/drive-audio"

[[ "${EUID}" -eq 0 ]] || { echo "Run as root (sudo)." >&2; exit 1; }
command="${1:-status}"

case "${command}" in
  start)
    [[ ! -s "${state_file}" ]] || { echo "A drive-test capture is already running: $(cat "${state_file}")" >&2; exit 2; }
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    session="${session_root}/${stamp}"
    mkdir -p "${session}"
    mkdir -p "${segment_dir}"
    rm -f "${segment_dir}"/*.wav
    chown n0jcg:n0jcg "${segment_dir}"
    mkdir -p "${dropin_dir}"
    printf '%s\n' '[Service]' \
      "Environment=APRS_AUDIO_SEGMENT_DIR=${segment_dir}" \
      'Environment=APRS_AUDIO_SEGMENT_SECONDS=60' >"${dropin_file}"
    systemctl daemon-reload
    start_iso="$(date -u --iso-8601=seconds)"
    printf 'started_utc=%s\nservice=%s\nfrequency_hz=%s\nrtl_serial=%s\nrtl_gain_db=%s\n' \
      "${start_iso}" "${service}" "${APRS_RTL_FREQUENCY_HZ:-144390000}" \
      "${APRS_RTL_SERIAL:-00014439}" "${RTL_GAIN_DB:-service-default}" >"${session}/metadata.txt"
    printf '%s\n' "${session}" >"${state_file}"
    journalctl -fu "${service}" -o short-iso >"${session}/live-journal.log" 2>&1 &
    echo "$!" >"${session}/journal.pid"
    systemctl restart "${service}"
    echo "Drive-test capture started: ${session}"
    ;;
  stop)
    [[ -s "${state_file}" ]] || { echo "No drive-test capture is running."; exit 0; }
    session="$(cat "${state_file}")"
    if [[ -s "${session}/journal.pid" ]]; then kill "$(cat "${session}/journal.pid")" 2>/dev/null || true; fi
    start_iso="$(sed -n 's/^started_utc=//p' "${session}/metadata.txt")"
    journalctl -u "${service}" --since "${start_iso}" -o short-iso >"${session}/service-journal.log" || true
    for name in rtl.log packets.log packet-records.jsonl audio-ring.wav direwolf.conf; do
      [[ -e "${runtime_dir}/${name}" ]] && cp -f "${runtime_dir}/${name}" "${session}/${name}"
    done
    [[ -d "${segment_dir}" ]] && cp -f "${segment_dir}"/*.wav "${session}/" 2>/dev/null || true
    rm -f "${dropin_file}"
    systemctl daemon-reload
    systemctl restart "${service}"
    end_iso="$(date -u --iso-8601=seconds)"
    printf 'ended_utc=%s\n' "${end_iso}" >>"${session}/metadata.txt"
    archive="${session}.tar.gz"
    tar -czf "${archive}" -C "${session_root}" "$(basename "${session}")"
    rm -f "${state_file}"
    echo "Drive-test capture saved: ${archive}"
    ;;
  status)
    if [[ -s "${state_file}" ]]; then
      echo "running: $(cat "${state_file}")"
    else
      echo "no drive-test capture running"
    fi
    systemctl --no-pager --full status "${service}" | sed -n '1,12p'
    ;;
  *)
    echo "Usage: $0 {start|stop|status}" >&2
    exit 2
    ;;
esac
