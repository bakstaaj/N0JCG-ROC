#!/usr/bin/env bash
set -euo pipefail

target_user="${1:-n0jcg}"
[[ "${target_user}" =~ ^[a-z_][a-z0-9_-]*$ ]] || {
  echo 'FINAL: FAIL - invalid target user'
  exit 1
}
id "${target_user}" >/dev/null 2>&1 || {
  echo "FINAL: FAIL - user does not exist: ${target_user}"
  exit 1
}

sudo -S -p '' usermod -aG dialout,audio "${target_user}"
echo "PASS ${target_user} is now a member of dialout and audio"
echo 'Reconnect sessions before probing radio devices.'
echo 'This script does not configure a modem, open a port, or transmit.'
echo 'FINAL: PASS'
