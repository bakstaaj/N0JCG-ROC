#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PACKAGE_FILE="${PROJECT_DIR}/config/base-packages.txt"
MODE=install

if [[ "${1:-}" == '--check-only' ]]; then
  MODE=check
elif [[ $# -ne 0 ]]; then
  echo 'Usage: install_base_tools.sh [--check-only]'
  exit 2
fi

[[ "$(id -un)" == n0jcg ]] || { echo 'FINAL: FAIL - run as n0jcg'; exit 1; }
[[ -f "${PACKAGE_FILE}" ]] || { echo 'FINAL: FAIL - package manifest missing'; exit 1; }
mapfile -t packages < <(grep -Ev '^[[:space:]]*(#|$)' "${PACKAGE_FILE}")
(( ${#packages[@]} > 0 )) || { echo 'FINAL: FAIL - package manifest empty'; exit 1; }

failures=0
for package in "${packages[@]}"; do
  candidate="$(apt-cache policy "${package}" | awk '/Candidate:/ {print $2}')"
  if [[ -z "${candidate}" || "${candidate}" == '(none)' ]]; then
    printf 'FAIL %-16s no candidate\n' "${package}"
    failures=$((failures + 1))
  elif dpkg-query -W -f='${Status}' "${package}" 2>/dev/null | grep -Fqx 'install ok installed'; then
    printf 'PASS %-16s installed candidate=%s\n' "${package}" "${candidate}"
  else
    printf 'READY %-15s candidate=%s\n' "${package}" "${candidate}"
  fi
done

(( failures == 0 )) || { echo "FINAL: FAIL - ${failures} unavailable packages"; exit 1; }
if [[ "${MODE}" == check ]]; then
  echo 'FINAL: PASS - package preflight only; no packages changed'
  exit 0
fi

sudo apt-get update
sudo env DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends -y "${packages[@]}"
"${PROJECT_DIR}/tools/validate_base_tools.sh"
