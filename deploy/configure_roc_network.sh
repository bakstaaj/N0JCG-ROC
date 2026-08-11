#!/usr/bin/env bash
set -euo pipefail

USB_IFACE="${USB_IFACE:-enx00e04c683f37}"
WIFI_IFACE="${WIFI_IFACE:-wlp2s0}"
STATIC_CIDR="${STATIC_CIDR:-192.168.68.114/24}"
GATEWAY="${GATEWAY:-192.168.68.1}"
USB_ROUTE_METRIC="${USB_ROUTE_METRIC:-100}"
WIFI_ROUTE_METRIC="${WIFI_ROUTE_METRIC:-600}"
ORIGIN_HINT="${ORIGIN_HINT:-50-cloud-init}"
NETPLAN_FILE="/etc/netplan/${ORIGIN_HINT}.yaml"
MODE="${1:---check-only}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo: sudo $0 --check-only|--apply" >&2
  exit 1
fi

if [[ "${MODE}" != "--check-only" && "${MODE}" != "--apply" ]]; then
  echo "Usage: sudo $0 --check-only|--apply" >&2
  exit 2
fi

for interface in "${USB_IFACE}" "${WIFI_IFACE}"; do
  if [[ ! -d "/sys/class/net/${interface}" ]]; then
    echo "Interface not found: ${interface}" >&2
    exit 1
  fi
done

if [[ ! -f "${NETPLAN_FILE}" ]]; then
  echo "Netplan file not found: ${NETPLAN_FILE}" >&2
  exit 1
fi

configure_root() {
  local root_dir="$1"
  netplan set --root-dir "${root_dir}" --origin-hint "${ORIGIN_HINT}" \
    "ethernets.${USB_IFACE}.dhcp4=false"
  netplan set --root-dir "${root_dir}" --origin-hint "${ORIGIN_HINT}" \
    "ethernets.${USB_IFACE}.addresses=[${STATIC_CIDR}]"
  netplan set --root-dir "${root_dir}" --origin-hint "${ORIGIN_HINT}" \
    "ethernets.${USB_IFACE}.gateway4=NULL"
  netplan set --root-dir "${root_dir}" --origin-hint "${ORIGIN_HINT}" \
    "ethernets.${USB_IFACE}.routes=[{\"to\":\"default\",\"via\":\"${GATEWAY}\",\"metric\":${USB_ROUTE_METRIC}}]"
  netplan set --root-dir "${root_dir}" --origin-hint "${ORIGIN_HINT}" \
    "wifis.${WIFI_IFACE}.dhcp4=true"
  netplan set --root-dir "${root_dir}" --origin-hint "${ORIGIN_HINT}" \
    "wifis.${WIFI_IFACE}.dhcp4-overrides.route-metric=${WIFI_ROUTE_METRIC}"
}

check_root="$(mktemp -d /tmp/n0jcg-netplan-check.XXXXXX)"
trap 'rm -rf -- "${check_root}"' EXIT
mkdir -p "${check_root}/etc/netplan"
cp -a "${NETPLAN_FILE}" "${check_root}${NETPLAN_FILE}"
configure_root "${check_root}"
netplan generate --root-dir "${check_root}"

echo "Validated network plan:"
netplan get --root-dir "${check_root}"

if [[ "${MODE}" == "--check-only" ]]; then
  exit 0
fi

backup_dir="/var/backups/n0jcg-roc-network-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "${backup_dir}"
cp -a "${NETPLAN_FILE}" "${backup_dir}/"
if [[ -f /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg ]]; then
  cp -a /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg "${backup_dir}/"
fi

rollback_script="/run/n0jcg-roc-network-rollback.sh"
cat >"${rollback_script}" <<EOF
#!/usr/bin/env bash
set -e
cp -a "${backup_dir}/$(basename "${NETPLAN_FILE}")" "${NETPLAN_FILE}"
if [[ -f "${backup_dir}/99-disable-network-config.cfg" ]]; then
  cp -a "${backup_dir}/99-disable-network-config.cfg" /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg
else
  rm -f /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg
fi
netplan generate
netplan apply
EOF
chmod 0600 "${rollback_script}"
systemd-run --quiet --unit=n0jcg-roc-network-rollback --on-active=2m /usr/bin/bash "${rollback_script}"

configure_root /
chmod 0600 "${NETPLAN_FILE}"
printf '%s\n' 'network: {config: disabled}' >/etc/cloud/cloud.cfg.d/99-disable-network-config.cfg
chmod 0644 /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg
netplan generate
netplan apply

sleep 3
usb_addresses="$(ip -4 address show dev "${USB_IFACE}")"
wifi_addresses="$(ip -4 address show dev "${WIFI_IFACE}")"
default_routes="$(ip route show default)"
grep -Fq "inet ${STATIC_CIDR}" <<<"${usb_addresses}"
grep -Fq 'inet ' <<<"${wifi_addresses}"
grep -Eq "default via ${GATEWAY} dev ${USB_IFACE}.*metric ${USB_ROUTE_METRIC}([[:space:]]|$)" <<<"${default_routes}"
grep -Eq "default .* dev ${WIFI_IFACE}.*metric ${WIFI_ROUTE_METRIC}([[:space:]]|$)" <<<"${default_routes}"

systemctl stop n0jcg-roc-network-rollback.timer
systemctl reset-failed n0jcg-roc-network-rollback.service 2>/dev/null || true
rm -f "${rollback_script}"

echo "Network configuration applied successfully. Backup: ${backup_dir}"
ip -br -4 address show dev "${USB_IFACE}"
ip -br -4 address show dev "${WIFI_IFACE}"
ip route show default
