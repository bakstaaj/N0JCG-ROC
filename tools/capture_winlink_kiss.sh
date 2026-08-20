#!/usr/bin/env bash
set -euo pipefail

# Protocol-neutral bounded capture for one operator-approved RF session.
# Captures both directions on the local LinBPQ/Dire Wolf KISS socket.
PORT="${WINLINK_KISS_PORT:-8010}"
DURATION="${WINLINK_KISS_SECONDS:-600}"
OUT_DIR="${WINLINK_KISS_CAPTURE_DIR:-/var/lib/n0jcg-winlink/diagnostics}"
[[ "${PORT}" =~ ^[0-9]+$ ]] && (( PORT > 0 && PORT < 65536 )) || { echo 'invalid KISS port' >&2; exit 2; }
[[ "${DURATION}" =~ ^[0-9]+$ ]] && (( DURATION >= 30 && DURATION <= 3600 )) || { echo 'invalid capture duration' >&2; exit 2; }
install -d -m 0750 -o n0jcg -g n0jcg "${OUT_DIR}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="${OUT_DIR}/kiss-${PORT}-${stamp}.pcap"
timeout "${DURATION}" tcpdump -i lo -nn -s 0 -U -w "${out}" "tcp port ${PORT}"
chown n0jcg:n0jcg "${out}" 2>/dev/null || true
# Retain the ten newest captures and remove no active/current file.
find "${OUT_DIR}" -maxdepth 1 -type f -name "kiss-${PORT}-*.pcap" -printf '%T@ %p\n' \
  | sort -nr | tail -n +11 | cut -d' ' -f2- | xargs -r rm -f
echo "capture=${out}"
