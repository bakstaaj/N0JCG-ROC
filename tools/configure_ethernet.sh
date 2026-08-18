#!/usr/bin/env bash
set -euo pipefail

ORIGIN_HINT="${ORIGIN_HINT:-50-cloud-init}"
NETPLAN_FILE="/etc/netplan/${ORIGIN_HINT}.yaml"
STATE_DIR="${STATE_DIR:-/run/n0jcg-operator-helper}"
PENDING_FILE="${STATE_DIR}/ethernet-pending.json"
MODE="${1:---status-json}"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ "${EUID}" -eq 0 ]] || fail "run as root"
for command in ip jq netplan systemd-run python3; do
  command -v "${command}" >/dev/null || fail "required command is not installed: ${command}"
done
[[ -f "${NETPLAN_FILE}" ]] || fail "Netplan file not found: ${NETPLAN_FILE}"
install -d -m 0750 "${STATE_DIR}"

ethernet_interface() {
  local candidate
  candidate="$(ip -4 route show default | awk '$1 == "default" {print $5; exit}')"
  if [[ -n "${candidate}" && "${candidate}" != "lo" && ! -d "/sys/class/net/${candidate}/wireless" ]]; then
    printf '%s\n' "${candidate}"
    return
  fi
  for candidate_path in /sys/class/net/*; do
    candidate="${candidate_path##*/}"
    [[ "${candidate}" != "lo" && ! -d "${candidate_path}/wireless" ]] || continue
    ip -4 address show dev "${candidate}" | grep -q 'inet ' && { printf '%s\n' "${candidate}"; return; }
  done
  return 1
}

status_json() {
  local interface address gateway dns pending
  interface="$(ethernet_interface || true)"
  address=""
  gateway=""
  dns=""
  if [[ -n "${interface}" ]]; then
    address="$(ip -4 -o address show dev "${interface}" scope global | awk 'NR == 1 {print $4}')"
    gateway="$(ip -4 route show default dev "${interface}" | awk '$1 == "default" {print $3; exit}')"
    if command -v resolvectl >/dev/null; then
      dns="$(resolvectl dns "${interface}" 2>/dev/null | sed -E 's/^[^:]+:[[:space:]]*//' | tr ' ' ',' || true)"
    fi
  fi
  pending=false
  [[ -s "${PENDING_FILE}" ]] && pending=true
  jq -cn \
    --arg interface "${interface}" \
    --arg address_cidr "${address}" \
    --arg gateway "${gateway}" \
    --arg dns "${dns}" \
    --argjson pending "${pending}" \
    '{interface: $interface, address_cidr: $address_cidr, gateway: $gateway, dns: $dns, pending: $pending}'
}

if [[ "${MODE}" == "--status-json" ]]; then
  status_json
  exit 0
fi

if [[ "${MODE}" == "--confirm" ]]; then
  [[ -s "${PENDING_FILE}" ]] || fail "there is no pending Ethernet change"
  interface="$(jq -r '.interface' "${PENDING_FILE}")"
  address_cidr="$(jq -r '.address_cidr' "${PENDING_FILE}")"
  old_address="$(jq -r '.old_address // ""' "${PENDING_FILE}")"
  rollback_unit="$(jq -r '.rollback_unit' "${PENDING_FILE}")"
  ip -4 address show dev "${interface}" | grep -Fq "inet ${address_cidr}" \
    || fail "the pending static address is not active"
  systemctl stop "${rollback_unit}.timer" 2>/dev/null || true
  systemctl reset-failed "${rollback_unit}.service" 2>/dev/null || true
  if [[ -n "${old_address}" && "${old_address}" != "${address_cidr}" ]]; then
    ip address del "${old_address}" dev "${interface}" 2>/dev/null || true
  fi
  rm -f -- "$(jq -r '.rollback_script' "${PENDING_FILE}")" "${PENDING_FILE}"
  status_json
  exit 0
fi

[[ "${MODE}" == "--set" && $# -eq 5 ]] || fail "usage: $0 --set INTERFACE ADDRESS/PREFIX GATEWAY DNS1,DNS2"
[[ ! -e "${PENDING_FILE}" ]] || fail "an Ethernet change is already pending confirmation"
interface="$2"
address_cidr="$3"
gateway="$4"
dns_csv="$5"
[[ "${interface}" =~ ^[a-zA-Z0-9_.:-]{1,32}$ && -d "/sys/class/net/${interface}" ]] || fail "Ethernet interface is invalid"
[[ "${interface}" != "lo" && ! -d "/sys/class/net/${interface}/wireless" ]] || fail "interface is not wired Ethernet"

validation="$(python3 - "${address_cidr}" "${gateway}" "${dns_csv}" <<'PY'
import ipaddress, json, sys
interface = ipaddress.IPv4Interface(sys.argv[1])
gateway = ipaddress.IPv4Address(sys.argv[2])
if gateway not in interface.network or gateway in {interface.ip, interface.network.network_address, interface.network.broadcast_address}:
    raise SystemExit("gateway must be a usable address in the static IP subnet")
dns = [str(ipaddress.IPv4Address(item.strip())) for item in sys.argv[3].split(",") if item.strip()]
if not 1 <= len(dns) <= 4:
    raise SystemExit("provide one to four IPv4 DNS servers")
print(json.dumps({"address": str(interface), "gateway": str(gateway), "dns": dns}))
PY
)" || fail "static IPv4 settings are invalid"
address_cidr="$(jq -r '.address' <<<"${validation}")"
gateway="$(jq -r '.gateway' <<<"${validation}")"
mapfile -t dns_servers < <(jq -r '.dns[]' <<<"${validation}")
old_address="$(ip -4 -o address show dev "${interface}" scope global | awk 'NR == 1 {print $4}')"

work_dir="$(mktemp -d /tmp/n0jcg-ethernet.XXXXXX)"
rollback_unit="n0jcg-ethernet-rollback-$$"
rollback_script="${STATE_DIR}/${rollback_unit}.sh"
cleanup() { rm -rf -- "${work_dir}"; }
trap cleanup EXIT
staged_root="${work_dir}/root"
mkdir -p "${staged_root}/etc"
cp -a /etc/netplan "${staged_root}/etc/"

definition="$(jq -cn \
  --arg address "${address_cidr}" \
  --arg gateway "${gateway}" \
  --argjson dns "$(printf '%s\n' "${dns_servers[@]}" | jq -R . | jq -s .)" \
  '{dhcp4: false, optional: true, addresses: [$address], nameservers: {addresses: $dns}, routes: [{to: "default", via: $gateway, metric: 100}]}')"
netplan set --root-dir "${staged_root}" --origin-hint "${ORIGIN_HINT}" "ethernets.${interface}=NULL"
netplan set --root-dir "${staged_root}" --origin-hint "${ORIGIN_HINT}" "ethernets.${interface}=${definition}"
netplan generate --root-dir "${staged_root}"

backup_dir="/var/backups/n0jcg-roc-ethernet-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "${backup_dir}"
cp -a /etc/netplan/. "${backup_dir}/"
cat >"${rollback_script}" <<EOF
#!/usr/bin/env bash
set -e
rm -f /etc/netplan/*.yaml
cp -a "${backup_dir}"/. /etc/netplan/
netplan generate
netplan apply
rm -f "${PENDING_FILE}" "${rollback_script}"
EOF
chmod 0700 "${rollback_script}"
jq -cn \
  --arg interface "${interface}" \
  --arg address_cidr "${address_cidr}" \
  --arg old_address "${old_address}" \
  --arg rollback_unit "${rollback_unit}" \
  --arg rollback_script "${rollback_script}" \
  '{interface: $interface, address_cidr: $address_cidr, old_address: $old_address, rollback_unit: $rollback_unit, rollback_script: $rollback_script}' \
  >"${PENDING_FILE}"
chmod 0600 "${PENDING_FILE}"
systemd-run --quiet --unit="${rollback_unit}" --on-active=3m /usr/bin/bash "${rollback_script}"

install -m 0600 "${staged_root}${NETPLAN_FILE}" "${NETPLAN_FILE}"
if ! netplan generate || ! netplan apply; then
  /usr/bin/bash "${rollback_script}"
  fail "Netplan apply failed and the previous configuration was restored"
fi
if ! ip -4 address show dev "${interface}" | grep -Fq "inet ${address_cidr}" \
  || ! ip -4 route show default dev "${interface}" | grep -Fq "via ${gateway}"; then
  /usr/bin/bash "${rollback_script}"
  fail "static address verification failed and the previous configuration was restored"
fi
if [[ -n "${old_address}" && "${old_address}" != "${address_cidr}" ]] \
  && ! ip -4 address show dev "${interface}" | grep -Fq "inet ${old_address}"; then
  ip address add "${old_address}" dev "${interface}"
fi
status_json
