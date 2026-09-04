#!/usr/bin/env bash
set -euo pipefail

# Run three equal receive-only phases at different RTL-SDR gains.  No transmit
# settings are changed; each phase restarts only the APRS receive listener.
runtime_dir="${APRS_RUNTIME_DIR:-/home/n0jcg/sdrdev/N0JCG-ROC/runtime/aprs}"
root_dir="${APRS_GAIN_TEST_ROOT:-/var/lib/n0jcg-roc/aprs-gain-tests}"
state_file="/run/n0jcg-aprs-gain-test"
service="n0jcg-aprs-rx.service"
dropin_dir="/etc/systemd/system/${service}.d"
dropin_file="${dropin_dir}/zz-gain-test.conf"
legacy_dropin_file="${dropin_dir}/gain-test.conf"
segment_dir="${runtime_dir}/gain-test-audio"
phase_seconds="${APRS_GAIN_TEST_PHASE_SECONDS:-600}"

[[ "${EUID}" -eq 0 ]] || { echo 'Run as root (sudo).' >&2; exit 1; }
command="${1:-status}"

run_test() {
  local session="$1"; shift
  local -a gains=("$@")
  trap 'rm -f "${dropin_file}" "${legacy_dropin_file}"; systemctl daemon-reload; systemctl restart "${service}"; rm -f "${state_file}"' EXIT INT TERM
  mkdir -p "${session}" "${segment_dir}" "${dropin_dir}"
  rm -f "${segment_dir}"/*.wav
  chown n0jcg:n0jcg "${segment_dir}"
  printf 'started_utc=%s\nphase_seconds=%s\ngains_db=%s\nfrequency_hz=%s\nrtl_serial=%s\n' \
    "$(date -u --iso-8601=seconds)" "${phase_seconds}" "${gains[*]}" \
    "${APRS_RTL_FREQUENCY_HZ:-144390000}" "${APRS_RTL_SERIAL:-00014439}" >"${session}/metadata.txt"
  for index in "${!gains[@]}"; do
    local gain="${gains[${index}]}"
    local phase="${session}/phase-$((index + 1))-${gain}db"
    local started
    mkdir -p "${phase}"
    rm -f "${segment_dir}"/*.wav
    printf '%s\n' '[Service]' \
      "Environment=RTL_GAIN_DB=${gain}" \
      "Environment=APRS_AUDIO_SEGMENT_DIR=${segment_dir}" \
      'Environment=APRS_AUDIO_SEGMENT_SECONDS=60' \
      'Environment=APRS_DIREWOLF_AUDIO_STATS_SECONDS=1' >"${dropin_file}"
    systemctl daemon-reload
    systemctl restart "${service}"
    started="$(date -u --iso-8601=seconds)"
    printf 'gain_db=%s\nstarted_utc=%s\n' "${gain}" "${started}" >"${phase}/metadata.txt"
    journalctl -fu "${service}" -o short-iso >"${phase}/live-journal.log" 2>&1 &
    local journal_pid=$!
    sleep "${phase_seconds}"
    kill "${journal_pid}" 2>/dev/null || true
    journalctl -u "${service}" --since "${started}" -o short-iso >"${phase}/service-journal.log" || true
    for name in rtl.log packets.log packet-records.jsonl audio-ring.wav direwolf.conf; do
      [[ -e "${runtime_dir}/${name}" ]] && cp -f "${runtime_dir}/${name}" "${phase}/${name}"
    done
    cp -f "${segment_dir}"/*.wav "${phase}/" 2>/dev/null || true
    # Use this phase's journal slice for the count: packets.log is append-only
    # and includes records from earlier runs. Count RF-decoded lines containing
    # BADGR anywhere in the header, including a digipeater path hop; exclude
    # [ig] and [ig>tx] APRS-IS lines.
    badger_count="$(grep -cE '\[[0-9.]+\][[:space:]].*BADGR' "${phase}/service-journal.log" 2>/dev/null || true)"
    read -r audio_min audio_max audio_avg < <(awk '/receive audio level CH0/ {for (i=1; i<=NF; i++) if ($i == "CH0") {gsub(/[^0-9.]/, "", $(i+1)); v=$(i+1)+0; if (n == 0 || v < lo) lo=v; if (n == 0 || v > hi) hi=v; sum+=v; n++}} END {if (n) printf "%s %s %.1f\n", lo, hi, sum/n; else print "— — —"}' "${phase}/service-journal.log")
    printf 'badger_packets=%s\naudio_level_min=%s\naudio_level_max=%s\naudio_level_average=%s\n' \
      "${badger_count}" "${audio_min}" "${audio_max}" "${audio_avg}" >"${phase}/summary.txt"
    printf 'ended_utc=%s\n' "$(date -u --iso-8601=seconds)" >>"${phase}/metadata.txt"
  done
  printf 'ended_utc=%s\n' "$(date -u --iso-8601=seconds)" >>"${session}/metadata.txt"
  tar -czf "${session}.tar.gz" -C "${root_dir}" "$(basename "${session}")"
  echo "Gain test complete: ${session}.tar.gz"
}

case "${command}" in
  start)
    [[ ! -s "${state_file}" ]] || { echo "A gain test is already running: $(cat "${state_file}")" >&2; exit 2; }
    shift
    if [[ "$#" -eq 0 ]]; then set -- 29.7 32.8 33.8; fi
    [[ "$#" -eq 3 ]] || { echo 'Usage: sudo aprs_gain_test.sh start [gain1 gain2 gain3]' >&2; exit 2; }
    for gain in "$@"; do [[ "${gain}" =~ ^[0-9]+([.][0-9]+)?$ ]] || { echo "Invalid gain: ${gain}" >&2; exit 2; }; done
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"; session="${root_dir}/${stamp}"
    printf '%s\n' "${session}" >"${state_file}"
    nohup "$0" __run "${session}" "$@" >/var/log/n0jcg-aprs-gain-test.log 2>&1 &
    echo "Gain test started: ${session} (${phase_seconds}s per gain)"
    ;;
  __run) shift; run_test "$@" ;;
  status)
    [[ -s "${state_file}" ]] && echo "running: $(cat "${state_file}")" || echo 'no gain test running'
    systemctl --no-pager --full status "${service}" | sed -n '1,12p'
    ;;
  stop)
    [[ -s "${state_file}" ]] || { echo 'No gain test is running.'; exit 0; }
    session="$(cat "${state_file}")"; pkill -f "${0} __run ${session}" 2>/dev/null || true
    rm -f "${dropin_file}" "${legacy_dropin_file}"; systemctl daemon-reload; systemctl restart "${service}"; rm -f "${state_file}"
    echo "Gain test stopped: ${session}"
    ;;
  *) echo "Usage: $0 {start|status|stop}" >&2; exit 2 ;;
esac
