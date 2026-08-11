#!/usr/bin/env bash
set -euo pipefail

MODE="${1:---check-only}"
LINBPQ_URL="https://www.cantab.net/users/john.wiseman/Downloads/linbpq64"
LINBPQ_SHA256="5dd2fc0636fd5db84521326c15e34fa71be28ed50696296d8f635c6fc8053825"
HTML_URL="https://www.cantab.net/users/john.wiseman/Downloads/HTMLPages.zip"
HTML_SHA256="773f997fe3255098aed7518d53d94f62a1a7354e7485dbf25bcfb36982224e2b"

if [[ "${MODE}" != "--check-only" && "${MODE}" != "--install" ]]; then
  echo "Usage: sudo $0 --check-only|--install" >&2
  exit 2
fi

[[ "$(uname -m)" == "x86_64" ]] || {
  echo "This pinned LinBPQ binary is for x86_64 only" >&2
  exit 1
}
for command_name in curl sha256sum unzip install; do
  command -v "${command_name}" >/dev/null || {
    echo "Missing command: ${command_name}" >&2
    exit 1
  }
done

if [[ "${MODE}" == "--check-only" ]]; then
  echo "PASS x86_64 host and LinBPQ installer dependencies are ready"
  echo "LinBPQ will remain disabled after installation"
  exit 0
fi

[[ "${EUID}" -eq 0 ]] || {
  echo "Run installation with sudo" >&2
  exit 1
}

stage="$(mktemp -d /tmp/n0jcg-linbpq.XXXXXX)"
trap 'rm -rf -- "${stage}"' EXIT
curl --fail --location --silent --show-error "${LINBPQ_URL}" -o "${stage}/linbpq"
curl --fail --location --silent --show-error "${HTML_URL}" -o "${stage}/HTMLPages.zip"
echo "${LINBPQ_SHA256}  ${stage}/linbpq" | sha256sum --check --status
echo "${HTML_SHA256}  ${stage}/HTMLPages.zip" | sha256sum --check --status

install -d -m 0755 /opt/n0jcg/linbpq
install -m 0755 "${stage}/linbpq" /opt/n0jcg/linbpq/linbpq
install -d -o n0jcg -g n0jcg -m 0750 /var/lib/n0jcg-winlink
install -d -o n0jcg -g n0jcg -m 0750 /var/lib/n0jcg-winlink/HTML
unzip -q -o "${stage}/HTMLPages.zip" -d /var/lib/n0jcg-winlink/HTML
chown -R n0jcg:n0jcg /var/lib/n0jcg-winlink/HTML

install -m 0644 deploy/n0jcg-winlink-modem.service /etc/systemd/system/n0jcg-winlink-modem.service
install -m 0644 deploy/n0jcg-winlink-rms.service /etc/systemd/system/n0jcg-winlink-rms.service
systemctl daemon-reload
systemctl disable n0jcg-winlink-modem.service n0jcg-winlink-rms.service >/dev/null 2>&1 || true

echo "PASS LinBPQ installed with pinned checksums; Winlink services remain disabled"
