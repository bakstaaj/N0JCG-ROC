#!/usr/bin/env bash
set -euo pipefail

[[ "$(id -u)" -eq 0 ]] || { echo 'Run with sudo.'; exit 1; }
ENV_FILE='/etc/n0jcg/operator-controls.env'

read -r -s -p 'New ROC operator password (minimum 10 characters): ' password
echo
read -r -s -p 'Confirm ROC operator password: ' confirmation
echo
[[ "${password}" == "${confirmation}" ]] || { echo 'Passwords do not match.'; exit 1; }

record="$(printf '%s' "${password}" | /usr/bin/python3 -c '
import hashlib
import secrets
import sys
password = sys.stdin.read()
if len(password) < 10:
    raise SystemExit("Password must contain at least 10 characters.")
iterations = 600000
salt = secrets.token_bytes(16)
digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
print(f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}")
')"
unset password confirmation
session_secret="$(/usr/bin/python3 -c 'import secrets; print(secrets.token_hex(32))')"

install -d -m 0750 -o root -g n0jcg /etc/n0jcg
temporary="$(mktemp /etc/n0jcg/operator-controls.env.XXXXXX)"
trap 'rm -f "${temporary}"' EXIT
printf 'ROC_OPERATOR_PASSWORD_HASH=%s\nROC_OPERATOR_SESSION_SECRET=%s\n' "${record}" "${session_secret}" > "${temporary}"
chown root:n0jcg "${temporary}"
chmod 0640 "${temporary}"
mv -f "${temporary}" "${ENV_FILE}"
trap - EXIT
systemctl restart n0jcg-roc.service
echo 'Operator controls configured. Existing browser sessions were invalidated.'
