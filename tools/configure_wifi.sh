#!/usr/bin/env bash
set -euo pipefail

WIFI_IFACE="${WIFI_IFACE:-wlp2s0}"
WIFI_ROUTE_METRIC="${WIFI_ROUTE_METRIC:-600}"
ORIGIN_HINT="${ORIGIN_HINT:-50-cloud-init}"
NETPLAN_FILE="/etc/netplan/${ORIGIN_HINT}.yaml"
ROLLBACK_DIR="${ROLLBACK_DIR:-/run}"
MODE="${1:-interactive}"
TARGET_SSID="${2:-}"

usage() {
  cat <<'EOF'
Usage:
  sudo tools/configure_wifi.sh
  sudo tools/configure_wifi.sh --scan-only

Environment overrides:
  WIFI_IFACE=wlp2s0 WIFI_ROUTE_METRIC=600 ORIGIN_HINT=50-cloud-init

The interactive mode scans for visible Wi-Fi networks, removes duplicate
SSIDs, validates a WPA-Personal password, creates a Netplan backup, applies
the selected network, and automatically rolls back if association fails.
EOF
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

if [[ "${MODE}" == "--help" || "${MODE}" == "-h" ]]; then
  usage
  exit 0
fi
if [[ "${MODE}" != "interactive" && "${MODE}" != "--scan-only" \
  && "${MODE}" != "--scan-json" && "${MODE}" != "--connect" ]]; then
  usage >&2
  exit 2
fi
if [[ "${MODE}" == "--connect" && -z "${TARGET_SSID}" ]]; then
  fail "--connect requires an SSID"
fi
if [[ "${EUID}" -ne 0 ]]; then
  fail "run with sudo: sudo $0 ${MODE/interactive/}"
fi

for command in iw netplan jq awk sort systemd-run; do
  command -v "${command}" >/dev/null || fail "required command is not installed: ${command}"
done
[[ -d "/sys/class/net/${WIFI_IFACE}" ]] || fail "Wi-Fi interface not found: ${WIFI_IFACE}"
[[ -f "${NETPLAN_FILE}" ]] || fail "Netplan file not found: ${NETPLAN_FILE}"

work_dir="$(mktemp -d /tmp/n0jcg-wifi.XXXXXX)"
rollback_unit="n0jcg-wifi-rollback-$$"
rollback_script="${ROLLBACK_DIR}/${rollback_unit}.sh"
cleanup() {
  rm -rf -- "${work_dir}"
}
trap cleanup EXIT

scan_file="${work_dir}/scan.txt"
network_file="${work_dir}/networks.tsv"

if [[ "${MODE}" != "--scan-json" && "${MODE}" != "--connect" ]]; then
  printf 'Scanning visible Wi-Fi networks on %s...\n' "${WIFI_IFACE}"
fi
scan_complete=0
for attempt in 1 2 3; do
  if iw dev "${WIFI_IFACE}" scan >"${scan_file}" 2>"${work_dir}/scan-error.txt"; then
    scan_complete=1
    break
  fi
  ((attempt < 3)) && sleep 2
done
if ((scan_complete == 0)); then
  scan_error="$(<"${work_dir}/scan-error.txt")"
  fail "Wi-Fi scan failed${scan_error:+: ${scan_error}}"
fi

awk '
  function emit() {
    if (ssid != "") {
      security = secured ? "Secured" : "Open"
      printf "%s\t%s\t%s\n", signal, security, ssid
    }
  }
  /^BSS / {
    emit()
    ssid = ""
    signal = -999
    secured = 0
    next
  }
  /^[[:space:]]*signal:/ {
    signal = $2
    next
  }
  /^[[:space:]]*SSID:/ {
    line = $0
    sub(/^[[:space:]]*SSID:[[:space:]]*/, "", line)
    ssid = line
    next
  }
  /^[[:space:]]*(RSN|WPA):/ {
    secured = 1
  }
  END { emit() }
' "${scan_file}" \
  | sort -t $'\t' -k1,1nr \
  | awk -F $'\t' '!seen[$3]++' >"${network_file}"

mapfile -t networks <"${network_file}"
((${#networks[@]} > 0)) || fail "no visible SSIDs were found"

if [[ "${MODE}" == "--scan-json" ]]; then
  jq -Rn '[inputs | split("\t") | {signal_dbm: (.[0] | tonumber), secured: (.[1] == "Secured"), ssid: .[2]}]' <"${network_file}"
  exit 0
fi

if [[ "${MODE}" == "interactive" || "${MODE}" == "--scan-only" ]]; then
  printf '\nAvailable Wi-Fi networks (strongest duplicate retained):\n'
  for index in "${!networks[@]}"; do
    IFS=$'\t' read -r signal security ssid <<<"${networks[$index]}"
    printf '  %2d) %-7s %7s dBm  %s\n' "$((index + 1))" "${security}" "${signal}" "${ssid}"
  done
fi

if [[ "${MODE}" == "--scan-only" ]]; then
  printf '\n%d unique visible SSIDs found.\n' "${#networks[@]}"
  exit 0
fi

if [[ "${MODE}" == "--connect" ]]; then
  selection=""
  for index in "${!networks[@]}"; do
    IFS=$'\t' read -r _ _ candidate_ssid <<<"${networks[$index]}"
    if [[ "${candidate_ssid}" == "${TARGET_SSID}" ]]; then
      selection="$((index + 1))"
      break
    fi
  done
  [[ -n "${selection}" ]] || fail "selected SSID is not currently visible: ${TARGET_SSID}"
else
  selection=""
  while true; do
    read -r -p $'\nSelect a network by number: ' selection
    if [[ "${selection}" =~ ^[0-9]+$ ]] && ((selection >= 1 && selection <= ${#networks[@]})); then
      break
    fi
    printf 'Enter a number from 1 through %d.\n' "${#networks[@]}" >&2
  done
fi

IFS=$'\t' read -r selected_signal selected_security selected_ssid <<<"${networks[$((selection - 1))]}"
password=""
if [[ "${selected_security}" == "Secured" ]]; then
  while true; do
    if [[ "${MODE}" == "--connect" ]]; then
      IFS= read -r password
      confirmation="${password}"
    else
      read -r -s -p "Password for ${selected_ssid}: " password
      printf '\n'
      read -r -s -p 'Confirm password: ' confirmation
      printf '\n'
      if [[ "${password}" != "${confirmation}" ]]; then
        printf 'Passwords do not match. Try again.\n' >&2
        continue
      fi
    fi
    password_length="$(printf '%s' "${password}" | wc -c)"
    if ((password_length >= 8 && password_length <= 63)); then
      break
    fi
    if ((password_length == 64)) && [[ "${password}" =~ ^[[:xdigit:]]{64}$ ]]; then
      break
    fi
    if [[ "${MODE}" == "--connect" ]]; then
      fail "WPA-Personal passwords must be 8-63 characters, or exactly 64 hexadecimal characters"
    fi
    printf 'WPA-Personal passwords must be 8-63 characters, or exactly 64 hexadecimal characters.\n' >&2
  done
elif [[ "${MODE}" != "--connect" ]]; then
  read -r -p "${selected_ssid} appears open. Connect without a password? [y/N] " open_confirmation
  [[ "${open_confirmation}" =~ ^[Yy]$ ]] || fail "connection cancelled"
fi

staged_root="${work_dir}/root"
mkdir -p "${staged_root}/etc"
cp -a /etc/netplan "${staged_root}/etc/"

if [[ "${selected_security}" == "Secured" ]]; then
  access_points="$(jq -cn --arg ssid "${selected_ssid}" --arg password "${password}" \
    '{($ssid): {password: $password}}')"
else
  access_points="$(jq -cn --arg ssid "${selected_ssid}" '{($ssid): {}}')"
fi
wifi_definition="$(jq -cn \
  --argjson access_points "${access_points}" \
  --argjson route_metric "${WIFI_ROUTE_METRIC}" \
  '{dhcp4: true, optional: true, "dhcp4-overrides": {"route-metric": $route_metric}, "access-points": $access_points}')"

netplan set --root-dir "${staged_root}" --origin-hint "${ORIGIN_HINT}" \
  "wifis.${WIFI_IFACE}=NULL"
netplan set --root-dir "${staged_root}" --origin-hint "${ORIGIN_HINT}" \
  "wifis.${WIFI_IFACE}=${wifi_definition}"
netplan generate --root-dir "${staged_root}"

printf '\nSelected SSID: %s\n' "${selected_ssid}"
printf 'Interface: %s\n' "${WIFI_IFACE}"
printf 'Wi-Fi route metric: %s (Ethernet remains preferred when its metric is lower)\n' "${WIFI_ROUTE_METRIC}"
if [[ "${MODE}" != "--connect" ]]; then
  read -r -p 'Apply this Netplan configuration? [y/N] ' apply_confirmation
  [[ "${apply_confirmation}" =~ ^[Yy]$ ]] || fail "connection cancelled; no files were changed"
fi

backup_dir="/var/backups/n0jcg-roc-wifi-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "${backup_dir}"
cp -a /etc/netplan/. "${backup_dir}/"

cat >"${rollback_script}" <<EOF
#!/usr/bin/env bash
set -e
rm -f /etc/netplan/*.yaml
cp -a "${backup_dir}"/. /etc/netplan/
netplan generate
netplan apply
EOF
chmod 0700 "${rollback_script}"
systemctl stop "${rollback_unit}.timer" 2>/dev/null || true
systemctl reset-failed "${rollback_unit}.service" 2>/dev/null || true
systemd-run --quiet --unit="${rollback_unit}" --on-active=2m /usr/bin/bash "${rollback_script}"

install -m 0600 "${staged_root}${NETPLAN_FILE}" "${NETPLAN_FILE}"
if ! netplan generate || ! netplan apply; then
  printf 'Netplan apply failed; restoring %s.\n' "${backup_dir}" >&2
  /usr/bin/bash "${rollback_script}"
  exit 1
fi

connected=0
for _ in $(seq 1 30); do
  link_status="$(iw dev "${WIFI_IFACE}" link 2>/dev/null || true)"
  if grep -Fq "SSID: ${selected_ssid}" <<<"${link_status}" \
    && ip -4 address show dev "${WIFI_IFACE}" | grep -Fq 'inet '; then
    connected=1
    break
  fi
  sleep 1
done

if ((connected == 0)); then
  printf 'Could not confirm association with %s; restoring %s.\n' "${selected_ssid}" "${backup_dir}" >&2
  /usr/bin/bash "${rollback_script}"
  exit 1
fi

systemctl stop "${rollback_unit}.timer"
systemctl reset-failed "${rollback_unit}.service" 2>/dev/null || true
rm -f "${rollback_script}"
password=''
confirmation=''

printf '\nConnected successfully. Backup: %s\n' "${backup_dir}"
iw dev "${WIFI_IFACE}" link | sed -n '/Connected to/p; /SSID:/p; /signal:/p'
ip -brief -4 address show dev "${WIFI_IFACE}"
ip route show default
