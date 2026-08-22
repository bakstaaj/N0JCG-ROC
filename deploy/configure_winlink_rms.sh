#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-/etc/n0jcg/winlink-rms.env}"
PTT_DEVICE="/dev/serial/by-id/usb-Silicon_Labs_CP2102N_USB_to_UART_Bridge_Controller_30217bb31dc6ef11ba3469527a5e3baa-if00-port0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LINMAIL_TEMPLATE="${PROJECT_ROOT}/config/linmail.winlink-postoffice.example.cfg"

[[ "${EUID}" -eq 0 ]] || { echo "Run with sudo" >&2; exit 1; }
[[ -f "${ENV_FILE}" ]] || { echo "Missing ${ENV_FILE}" >&2; exit 1; }

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

required=(
  WINLINK_CMS_PASSWORD WINLINK_ADMIN_USER WINLINK_ADMIN_PASSWORD
  WINLINK_BASE_CALL WINLINK_GATEWAY_CALL WINLINK_LOCATOR WINLINK_FREQUENCY_HZ
  WINLINK_SERVICE_HOURS WINLINK_POWER_W WINLINK_ANTENNA_HEIGHT_FT
  WINLINK_ANTENNA_GAIN_DBI WINLINK_ANTENNA_DIRECTION_DEG WINLINK_PTT_ENABLED
)
for name in "${required[@]}"; do
  value="${!name:-}"
  [[ -n "${value}" && "${value}" != "CHANGE_ME" ]] || {
    echo "Missing required setting: ${name}" >&2
    exit 1
  }
done

[[ "${WINLINK_BASE_CALL}" =~ ^[A-Z0-9]{3,6}$ ]] || { echo "Invalid base call" >&2; exit 1; }
WINLINK_NODE_CALL="${WINLINK_NODE_CALL:-${WINLINK_BASE_CALL}-15}"
[[ "${WINLINK_NODE_CALL}" =~ ^[A-Z0-9]{3,6}-[0-9]{1,2}$ ]] || { echo "Invalid node call" >&2; exit 1; }
[[ "${WINLINK_GATEWAY_CALL}" =~ ^[A-Z0-9]{3,6}-[0-9]{1,2}$ ]] || { echo "Invalid gateway call" >&2; exit 1; }
[[ "${WINLINK_NODE_CALL}" != "${WINLINK_GATEWAY_CALL}" ]] || { echo "Node call must differ from gateway call" >&2; exit 1; }
[[ "${WINLINK_LOCATOR}" =~ ^[A-R]{2}[0-9]{2}[A-X]{2}$ ]] || { echo "Invalid Maidenhead locator" >&2; exit 1; }
[[ "${WINLINK_FREQUENCY_HZ}" =~ ^[0-9]{9}$ ]] || { echo "Frequency must be an integer in Hz" >&2; exit 1; }
[[ "${WINLINK_PTT_ENABLED}" == "0" || "${WINLINK_PTT_ENABLED}" == "1" ]] || { echo "WINLINK_PTT_ENABLED must be 0 or 1" >&2; exit 1; }

WINLINK_POST_OFFICE_ENABLED="${WINLINK_POST_OFFICE_ENABLED:-0}"
WINLINK_POST_OFFICE_CALL="${WINLINK_POST_OFFICE_CALL:-${WINLINK_BASE_CALL}-11}"
[[ "${WINLINK_POST_OFFICE_ENABLED}" == "0" || "${WINLINK_POST_OFFICE_ENABLED}" == "1" ]] || {
  echo "WINLINK_POST_OFFICE_ENABLED must be 0 or 1" >&2
  exit 1
}
[[ "${WINLINK_POST_OFFICE_CALL}" =~ ^[A-Z0-9]{3,6}-[0-9]{1,2}$ ]] || {
  echo "Invalid post office call" >&2
  exit 1
}
[[ "${WINLINK_POST_OFFICE_CALL}" != "${WINLINK_GATEWAY_CALL}" ]] || {
  echo "Post office call must differ from the RMS gateway call" >&2
  exit 1
}
[[ "${WINLINK_POST_OFFICE_CALL}" != "${WINLINK_NODE_CALL}" ]] || {
  echo "Post office call must differ from the LinBPQ node call" >&2
  exit 1
}
for reserved_call in "${WINLINK_BASE_CALL}-1" "${WINLINK_BASE_CALL}-2" "${WINLINK_BASE_CALL}-9"; do
  for service_call in "${WINLINK_NODE_CALL}" "${WINLINK_GATEWAY_CALL}" "${WINLINK_POST_OFFICE_CALL}"; do
    [[ "${service_call}" != "${reserved_call}" ]] || {
      echo "${service_call} is reserved for an N0JCG mobile/APRS client" >&2
      exit 1
    }
  done
done

VARA_FM_ENABLED="${VARA_FM_ENABLED:-0}"
VARA_FM_COMMAND_PORT="${VARA_FM_COMMAND_PORT:-8300}"
VARA_FM_DATA_PORT="${VARA_FM_DATA_PORT:-8301}"
VARA_FM_MODE="${VARA_FM_MODE:-FM1200}"
VARA_FM_REPORT_MODE="VARA${VARA_FM_MODE}"
[[ "${VARA_FM_ENABLED}" == "0" || "${VARA_FM_ENABLED}" == "1" ]] || {
  echo "VARA_FM_ENABLED must be 0 or 1" >&2
  exit 1
}
if [[ "${VARA_FM_ENABLED}" == "1" ]]; then
  [[ -n "${VARA_FM_EXE:-}" && -f "${VARA_FM_EXE}" ]] || {
    echo "VARA_FM_EXE must point to an installed VARA FM executable" >&2
    exit 1
  }
  [[ "${VARA_FM_CALL:-}" =~ ^[A-Z0-9]{3,6}-[0-9]{1,2}$ ]] || {
    echo "VARA_FM_CALL must be a gateway callsign with SSID" >&2
    exit 1
  }
  [[ "${VARA_FM_MODE}" == "FM1200" || "${VARA_FM_MODE}" == "FM9600" ]] || {
    echo "VARA_FM_MODE must be FM1200 or FM9600" >&2
    exit 1
  }
fi

install -d -m 0750 -o root -g n0jcg /etc/n0jcg
install -d -m 0750 -o n0jcg -g n0jcg /var/lib/n0jcg-winlink

ptt_line="# PTT disabled by WINLINK_PTT_ENABLED=0"
if [[ "${WINLINK_PTT_ENABLED}" == "1" ]]; then
  [[ -e "${PTT_DEVICE}" ]] || { echo "DigiRig PTT device is missing" >&2; exit 1; }
  ptt_line="PTT ${PTT_DEVICE} RTS"
fi

post_office_telnet_line="; Post Office disabled by WINLINK_POST_OFFICE_ENABLED=0"
post_office_application=""
post_office_start=""
if [[ "${WINLINK_POST_OFFICE_ENABLED}" == "1" ]]; then
  [[ -f "${LINMAIL_TEMPLATE}" ]] || { echo "Missing ${LINMAIL_TEMPLATE}" >&2; exit 1; }
  post_office_telnet_line="RELAYAPPL=BBS"
  post_office_application="APPLICATION 2,BBS,,${WINLINK_POST_OFFICE_CALL}"
  post_office_start="LINMAIL"
fi

vara_port=""
if [[ "${VARA_FM_ENABLED}" == "1" ]]; then
  vara_port="
PORT
 PORTNUM=3
 INTERLOCK=1
 ID=VARA FM
 DRIVER=VARA
 PORTCALL=${VARA_FM_CALL}
 SESSIONTIMELIMIT=30
 CONFIG
  ADDR 127.0.0.1 ${VARA_FM_COMMAND_PORT}
  ${VARA_FM_MODE}
  WL2KREPORT PUBLIC, api.winlink.org, 80, ${VARA_FM_CALL}, ${WINLINK_LOCATOR}, ${WINLINK_SERVICE_HOURS}, ${WINLINK_FREQUENCY_HZ}, ${VARA_FM_REPORT_MODE}, ${WINLINK_POWER_W}, ${WINLINK_ANTENNA_HEIGHT_FT}, ${WINLINK_ANTENNA_GAIN_DBI}, ${WINLINK_ANTENNA_DIRECTION_DEG}
  ****
 ENDPORT
"
fi

umask 077
cat > /etc/n0jcg/winlink-direwolf.conf <<EOF
ADEVICE plughw:CARD=Device,DEV=0
ACHANNELS 1
ARATE 48000
CHANNEL 0
MYCALL ${WINLINK_GATEWAY_CALL}
MODEM 1200
${ptt_line}
TXDELAY 50
TXTAIL 5
SLOTTIME 10
PERSIST 63
AGWPORT 0
KISSPORT 0
KISSPORT 8010
EOF
chown root:n0jcg /etc/n0jcg/winlink-direwolf.conf
chmod 0640 /etc/n0jcg/winlink-direwolf.conf

cat > /var/lib/n0jcg-winlink/bpq32.cfg <<EOF
SIMPLE
LOCATOR=${WINLINK_LOCATOR}
NODECALL=${WINLINK_NODE_CALL}
NODEALIAS=N0ROC

INFOMSG:
N0JCG Radio Operations Center - Cripple Creek, Colorado
***

IDMSG:
${WINLINK_GATEWAY_CALL} Winlink RMS Packet Gateway
${WINLINK_LOCATOR} - ${WINLINK_FREQUENCY_HZ} Hz
***
IDINTERVAL=10

BTEXT:
${WINLINK_GATEWAY_CALL} RMS Packet Gateway
${WINLINK_FREQUENCY_HZ} Hz - ${WINLINK_LOCATOR}
***
BTINTERVAL=30

PORT
 ID=CMS and management
 DRIVER=TELNET
 CONFIG
 LOGGING=1
 CMS=1
 CMSCALL=${WINLINK_BASE_CALL}
 CMSPASS=${WINLINK_CMS_PASSWORD}
 ${post_office_telnet_line}
 HTTPPORT=8088
 TCPPORT=8011
 FBBPORT=8012
 MAXSESSIONS=10
 CloseOnDisconnect=1
 USER=${WINLINK_ADMIN_USER},${WINLINK_ADMIN_PASSWORD},${WINLINK_BASE_CALL},"",SYSOP
ENDPORT

PORT
 PORTNUM=2
 ID=AnyTone 1200 baud packet
 TYPE=ASYNC
 PROTOCOL=KISS
 IPADDR=127.0.0.1
 TCPPORT=8010
 CHANNEL=A
 BCALL=${WINLINK_GATEWAY_CALL}
 FRACK=10000
 RESPTIME=3000
 RETRIES=10
 MAXFRAME=4
 PACLEN=200
 TXDELAY=500
 SLOTTIME=100
 PERSIST=64
 WL2KREPORT PUBLIC, api.winlink.org, 80, ${WINLINK_GATEWAY_CALL}, ${WINLINK_LOCATOR}, ${WINLINK_SERVICE_HOURS}, ${WINLINK_FREQUENCY_HZ}, PKT1200, ${WINLINK_POWER_W}, ${WINLINK_ANTENNA_HEIGHT_FT}, ${WINLINK_ANTENNA_GAIN_DBI}, ${WINLINK_ANTENNA_DIRECTION_DEG}
ENDPORT

${vara_port}

APPLICATION 1,RMS,C 1 CMS,${WINLINK_GATEWAY_CALL},N0RMS,255
${post_office_application}
${post_office_start}
EOF
chown n0jcg:n0jcg /var/lib/n0jcg-winlink/bpq32.cfg
chmod 0600 /var/lib/n0jcg-winlink/bpq32.cfg

if [[ "${WINLINK_POST_OFFICE_ENABLED}" == "1" ]]; then
  sed \
    -e "s/__POST_OFFICE_CALL__/${WINLINK_POST_OFFICE_CALL}/g" \
    -e "s/__BASE_CALL__/${WINLINK_BASE_CALL}/g" \
    "${LINMAIL_TEMPLATE}" > /var/lib/n0jcg-winlink/linmail.cfg
  chown n0jcg:n0jcg /var/lib/n0jcg-winlink/linmail.cfg
  chmod 0600 /var/lib/n0jcg-winlink/linmail.cfg
fi

if [[ ! -e /etc/n0jcg/winlink-rms-approved ]]; then
  install -m 0644 /dev/null /etc/n0jcg/winlink-rms-approved
fi

echo "PASS authorized RMS configuration generated"
if [[ "${WINLINK_PTT_ENABLED}" == "0" ]]; then
  echo "SAFE PTT remains disabled; services were not enabled or started"
else
  echo "WARNING PTT is configured; services were not enabled or started"
fi
if [[ "${WINLINK_POST_OFFICE_ENABLED}" == "1" ]]; then
  echo "PASS Winlink Express Post Office configured on TCP port 8772"
fi
