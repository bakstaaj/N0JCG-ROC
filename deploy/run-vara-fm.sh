#!/usr/bin/env bash
set -euo pipefail

: "${VARA_FM_ENABLED:=0}"
: "${VARA_FM_EXE:=/opt/n0jcg/vara-fm/VARAFM.exe}"
: "${VARA_FM_WINEPREFIX:=/var/lib/n0jcg-vara-fm/wine}"

if [[ "${VARA_FM_ENABLED}" != "1" ]]; then
  echo "VARA FM disabled by VARA_FM_ENABLED=0"
  exit 0
fi
[[ -x "$(command -v wine)" ]] || { echo "wine is not installed" >&2; exit 1; }
[[ -f "${VARA_FM_EXE}" ]] || { echo "Missing VARA FM executable: ${VARA_FM_EXE}" >&2; exit 1; }

install -d -m 0750 -o n0jcg -g n0jcg "${VARA_FM_WINEPREFIX}"
export WINEPREFIX="${VARA_FM_WINEPREFIX}"
export WINEDEBUG="${WINEDEBUG:--all}"

# VARA FM is a Windows modem. Xvfb gives it a stable display on a headless ROC;
# its audio device, FM mode, command/data ports, and PTT are set in VARA FM's
# own settings and are documented in docs/VARA_FM_COMMISSIONING.md.
exec xvfb-run --auto-servernum --server-args="-screen 0 1024x768x24" \
  wine "${VARA_FM_EXE}"
