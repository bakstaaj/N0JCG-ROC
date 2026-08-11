#!/usr/bin/env bash
set -euo pipefail

install -d -m 0755 /etc/systemd/logind.conf.d
install -m 0644 /tmp/10-n0jcg-lid.conf /etc/systemd/logind.conf.d/10-n0jcg-lid.conf

# The APRS station ID is sent directly to APRS-IS by the receive-only iGate.
# The former Pluto RF beacon is deliberately disabled.
systemctl disable --now n0jcg-aprs-beacon.service
systemctl restart systemd-logind.service
systemctl restart n0jcg-aprs-rx.service
