#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_DIR}"
export PYTHONPATH="${PROJECT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

for embedded_app in web/air-traffic web/pi-scanner; do
  if [[ -d "${embedded_app}" ]] && find "${embedded_app}" -type f -print -quit | grep -q .; then
    echo "FINAL: FAIL - ${embedded_app} must remain in its standalone repository"
    exit 1
  fi
done

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN=python
else
  echo 'FINAL: FAIL - Python 3 is not installed'
  exit 1
fi

"${PYTHON_BIN}" -m compileall -q src tests deploy/operator_helper.py tools/winlink_mail_event_logger.py
"${PYTHON_BIN}" -m unittest discover -s tests -v
bash -n tools/*.sh deploy/*.sh

if command -v node >/dev/null 2>&1; then
  node --check web/app.js
else
  echo 'INFO: node unavailable; JavaScript syntax check skipped'
fi

if grep -RIl $'\r' --include='*.py' --include='*.sh' --include='*.js' --include='*.css' --include='*.html' --include='*.md' .; then
  echo "FINAL: FAIL - CRLF files found"
  exit 1
fi

echo "FINAL: PASS"
