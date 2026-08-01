#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_DIR}"

failures=0

if git diff --check; then
  echo 'PASS unstaged diff has no whitespace errors'
else
  failures=$((failures + 1))
fi

if git diff --cached --check; then
  echo 'PASS staged diff has no whitespace errors'
else
  failures=$((failures + 1))
fi

for private_path in config/station.toml .server.env; do
  if git ls-files --error-unmatch "${private_path}" >/dev/null 2>&1; then
    echo "FAIL private file is tracked: ${private_path}"
    failures=$((failures + 1))
  elif git check-ignore -q "${private_path}"; then
    echo "PASS private file is ignored: ${private_path}"
  else
    echo "FAIL private file is not ignored: ${private_path}"
    failures=$((failures + 1))
  fi
done

if grep -RIl $'\r' \
  --exclude-dir=.git \
  --exclude='*.pyc' \
  --include='*.py' --include='*.sh' --include='*.js' --include='*.css' \
  --include='*.html' --include='*.md' --include='Makefile' .; then
  echo 'FAIL CRLF text files found'
  failures=$((failures + 1))
else
  echo 'PASS repository text files use LF endings'
fi

if grep -RIEln \
  --exclude-dir=.git \
  --exclude='*.pyc' \
  '(gh[opsu]_[A-Za-z0-9_]{20,}|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY)' .; then
  echo 'FAIL credential-like content found'
  failures=$((failures + 1))
else
  echo 'PASS no GitHub token or private-key material found'
fi

(( failures == 0 )) || { echo "FINAL: FAIL - ${failures} hygiene checks failed"; exit 1; }
echo 'FINAL: PASS'
