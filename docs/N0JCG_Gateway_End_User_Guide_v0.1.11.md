# N0JCG Gateway End User Guide

**Version:** 0.1.11

**Publication:** September 2026

**Audience:** Amateur Radio operators, station administrators, and maintainers

**Product:** N0JCG Gateway / Radio Operations Center

> Open radio systems, engineered as one platform.

## 1. About N0JCG Gateway

N0JCG Gateway is a Linux radio-station appliance and browser dashboard. It
combines live APRS reception, a receive-only APRS-IS iGate, Winlink RMS Packet,
a LAN Winlink Post Office, Ecowitt weather data, system readiness, and links to
other N0JCG operational applications.

The ROC presents observed state. A green service label means the underlying
service is running and its current health evidence is good; it is not a claim
about antenna coverage or guaranteed message delivery.

### What is included

- N0JCG Gateway dashboard and JSON APIs.
- RTL-SDR APRS reception with Dire Wolf.
- Receive-only APRS-IS forwarding and internet-only iGate identification.
- APRS frame history and optional aprs.fi station map.
- 1200-baud Winlink RMS Packet integration using Dire Wolf and LinBPQ.
- LAN Network Post Office access for Winlink Express.
- Ecowitt GW1100/WS90 weather monitoring.
- Protected administrative controls and privacy-safe diagnostics.
- Configurable launch links and health summaries for independently hosted
  N0JCG Air Traffic Center and N0JCG Scanner systems.

### What is not included

- A coordinated radio frequency, Winlink gateway authorization, or Amateur
  Radio license.
- N0JCG Air Traffic Center or N0JCG Scanner application code.
- VARA FM, digipeating, or browser-controlled RF test transmission.
- A guarantee that every radio, USB audio interface, or SDR uses the same
  device name or audio level.

## 2. Safety, licensing, and privacy

N0JCG Gateway is intended for use by a qualified Amateur Radio operator. The
operator remains responsible for station licensing, callsign use, frequency
coordination, permitted modes, transmit power, identification, RF exposure,
and local regulations. Winlink RMS authorization does not assign a frequency.

Before enabling any transmit-capable service:

1. Coordinate the channel locally and record the result.
2. Confirm the radio and DigiRig cable pinout.
3. Use a dummy load for PTT and audio-level tests that do not require an
   over-the-air peer.
4. Verify that one process owns the radio audio and PTT interfaces.
5. Begin at the minimum practical transmit power.
6. Confirm that PTT releases after every test and failure condition.

Keep passwords, passcodes, API keys, exact private coordinates, and remote
access credentials outside the repository. Protected settings belong in
`/etc/n0jcg/` with restrictive permissions. Mutable ROC state belongs in
`/var/lib/n0jcg-roc/`.

## 3. System requirements

### Supported host

- Ubuntu 24.04 LTS, x86-64.
- A dedicated local account named `n0jcg`.
- A wired or wireless LAN connection with a stable address or DHCP reservation.
- Python 3.11 or newer.
- Internet access for APRS-IS, aprs.fi, Winlink CMS, licensing, and updates.

### Optional hardware by service

| Service | Hardware |
|---|---|
| APRS RX iGate | RTL-SDR with a stable EEPROM serial and a 2 m antenna |
| Winlink RMS Packet | Supported VHF radio, DigiRig Mobile, radio-specific cable, antenna |
| Weather | Ecowitt GW1100 gateway and compatible outdoor sensor such as WS90 |
| Air Traffic Center | Independently installed N0JCG Air Traffic Center node |
| Scanner | Independently installed N0JCG Scanner node |

Use a powered USB hub when the host cannot reliably power all attached
devices. Identify RTL-SDRs by EEPROM serial rather than Linux device number.

## 4. Install the ROC dashboard

The release archive contains the complete repository snapshot. Install it at
the supported location:

```bash
sudo apt update
sudo apt install -y git python3 curl
sudo install -d -o n0jcg -g n0jcg /home/n0jcg/sdrdev
cd /home/n0jcg/sdrdev
tar -xzf N0JCG-ROC-v0.1.10.tar.gz
mv N0JCG-ROC-v0.1.10 N0JCG-ROC
cd N0JCG-ROC
```

Validate the source before installing the service:

```bash
./tools/validate.sh
./tools/install_base_tools.sh --check-only
```

Install the declared radio-tool baseline only after reviewing the package
list. Then install the dashboard service:

```bash
./tools/install_base_tools.sh
./tools/install_systemd_service.sh
```

Open `http://ROC_IP/` from a browser on the same network. The default service
listens on TCP port 80.

### Expected result

`n0jcg-roc.service` is active, the dashboard loads, and `/api/health` returns
JSON. Radio services may still show waiting or unavailable until configured.

## 5. First-run configuration

### Station overview

Open **Configuration** and set the Station overview title. Include the
operator's Amateur Radio callsign and a useful public location or description,
for example `W1ABC · County EOC`. Avoid a private street address.

### Registration and evaluation mode

An unregistered installation operates its data services for a five-minute
evaluation period. When that period expires, APRS, Weather, and Winlink
services stop and dashboard data pauses. **Restart Trial** becomes available
only after expiration.

Enter a valid N0JCG Gateway license serial in **Product registration** to enable
continuous operation. After successful activation the trial label and restart
button are hidden. Registration does not configure or authorize RF services.

### Independent application connections

In **Application connections**, configure Air Traffic Center and Scanner
separately. Each application has its own enable switch, host, and port, so they
may run on different computers. The ROC creates direct launch links and reads
only the application health data needed for its summary cards.

## 6. Dashboard tour

### Station overview and live summary

The top of the dashboard shows the configured station title, ROC health, and
summary cards for APRS, Winlink, Weather, and connected applications. A service
fault should be investigated before relying on the station unattended.

### APRS activity

**Latest APRS frame** shows the newest decoded frame, its RF or Internet origin,
and its UTC timestamp. Open it to view the full sortable history in pages of 25.
Each stored frame keeps its own timestamp; the list is not a live packet sniffer.

The optional APRS map displays callsigns heard by this ROC during the most
recent 24 hours. It requests current positions from aprs.fi and uses the APRS
symbol carried by the station report. Configure an aprs.fi API key and enable
the integration under **Configuration**. Disabling the switch stops requests
without deleting the saved key.

The map uses locally decoded RF frames from the `n0jcg-aprs-rx.service`
systemd journal. The ROC service must be able to read that journal; the
packaged `n0jcg-roc.service` unit grants the `systemd-journal` supplementary
group. Internet-only frames and frames that are not locally heard do not create
map callsigns.

### Winlink Gateway

The Winlink section reports:

- gateway callsign, mode, frequency, and CMS state;
- current radio link and connected remote callsign;
- sessions, success rate, bytes, and throughput during the last 24 hours;
- recent session results and duration; and
- BPQMail Pending, Delivered, Received, and Archived message counts.

**Pending** means mail still queued for delivery. **Delivered** means the local
store records successful forwarding or pickup. **Received** identifies inbound
mail records. **Archived** is a retained state, so a received message may also
be counted as archived; the four values are operational categories rather than
a single partition of all records.

### Weather monitor

Weather cards show the GW1100 connection plus temperature, humidity, pressure,
wind, rain, solar, UV, and sensor status when available. The observed timestamp
and stale label distinguish a working collector from an old reading.

### System readiness

System readiness shows host resources, attached hardware, APRS frame totals,
aircraft, P25 voice calls, and VHF/UHF locks where connected applications
provide those metrics. A remote-application metric is unavailable when its
connection is disabled or its API cannot be reached.

## 7. Configure APRS RX iGate

APRS reception uses an RTL-SDR and Dire Wolf on 144.390 MHz in North America.
The DigiRig audio interface is reserved for Winlink.

1. Set a unique RTL EEPROM serial and record it.
2. Copy `config/aprs-igate.env.example` to `/etc/n0jcg/aprs-igate.env`.
3. Enter the iGate callsign and APRS-IS passcode.
4. Protect the file with owner-only permissions.
5. Install and start `n0jcg-aprs-rx.service`.

Example protection:

```bash
sudo install -d -m 0755 /etc/n0jcg
sudo install -m 0600 config/aprs-igate.env.example /etc/n0jcg/aprs-igate.env
sudo editor /etc/n0jcg/aprs-igate.env
sudo systemctl daemon-reload
sudo systemctl enable --now n0jcg-aprs-rx.service
```

The iGate path is receive-only. Internet identification packets do not key a
radio. Confirm APRS-IS login verification in the service journal, then confirm
a locally decoded RF frame before treating the iGate as commissioned.

### Passive digipeater survey

The ROC includes a receive-only digipeater survey at the bottom of the APRS
activity panel. It reviews the recent RF frame history (72 hours by default)
and reports packets whose path contains a digipeater hop marked with `*`.
Common path aliases such as `WIDE`, `TRACE`, `RELAY`, `NCA`, and `SS` are
ignored, and APRS-IS-only frames are never counted as RF observations.

This is a passive planning tool: it does not transmit, query APRS-IS, or prove
that a digipeater is currently reachable. A result shows that the ROC heard a
frame after a digipeater had used it; an empty result means no qualifying hop
was decoded during the survey window. The displayed distance is the distance
from the decoded source station to the ROC, not the digipeater's location.

Use the survey before enabling any digipeater function. Coordinate a local
frequency and path policy first, and treat the survey as supporting evidence
for coverage planning rather than authorization to transmit.

## 8. Configure Ecowitt weather

Give the GW1100 a stable LAN address. Copy `config/weather.env.example` to
`/etc/n0jcg/weather.env`, replace `WEATHER_GATEWAY_IP`, and install or restart
`n0jcg-weather.service`.

```bash
sudo install -m 0600 config/weather.env.example /etc/n0jcg/weather.env
sudo editor /etc/n0jcg/weather.env
sudo systemctl enable --now n0jcg-weather.service
journalctl -u n0jcg-weather.service -n 30 --no-pager
```

The dashboard should show a current observation time and identify the outdoor
sensor. Pressure may be reported as absolute or relative depending on the
gateway data. Calibrate relative pressure in the Ecowitt system, not by
silently changing the ROC display.

### CWOP upload

The GW1100 does not upload directly to CWOP. The ROC converts the normalized
GW1100 observation into an APRS weather report and sends it to CWOP through
APRS-IS; this path never keys a radio. After CWOP assigns the station ID,
protect the following values in `/etc/n0jcg/weather.env`:

```bash
CWOP_STATION_ID=CWxxxx
# CWOP weather stations use the APRS-IS unverified passcode.
CWOP_APRS_PASSCODE=-1
CWOP_LATITUDE=38.800833
CWOP_LONGITUDE=-105.200167
CWOP_INTERVAL_SECONDS=300
```

Alternatively, unlock Protected operator controls in the ROC Configuration panel,
enter the CWOP station ID, station coordinates, and upload interval, and save.
The panel writes `/var/lib/n0jcg-roc/cwop.json`; this is the preferred path for
other operators because it does not require editing a service environment file.
The upload interval is constrained to 5 minutes through 1 hour. Then enable the
uploader:

```bash
sudo systemctl enable --now n0jcg-cwop-weather.service
journalctl -u n0jcg-cwop-weather.service -n 30 --no-pager
```

Confirm the station in the CWOP search tool after 5–15 minutes. The service is
safe to leave installed while unconfigured: it remains active but skips uploads
until the operator enables a complete CWOP configuration.

## 9. Commission Winlink RMS Packet

Do not begin this section until the gateway has Winlink authorization and a
locally coordinated frequency.

Copy `config/winlink-rms.env.example` to
`/etc/n0jcg/winlink-rms.env`. Enter the assigned identities, CMS password,
unique management password, grid square, coordinated frequency, service hours,
transmitter power, antenna height above local ground, antenna gain, and antenna
direction. Keep `WINLINK_PTT_ENABLED=0` during initial setup.

Generate the runtime files:

```bash
sudo deploy/install_linbpq.sh --install
sudo deploy/configure_winlink_rms.sh
```

Use the preflight and dummy-load procedures in
`docs/WINLINK_RMS_COMMISSIONING.md`. Confirm receive audio, PTT polarity,
transmit audio, clean release, local AX.25 connection, CMS connectivity, and
the Winlink channel report before unattended operation.

The service names are:

- `n0jcg-winlink-modem.service` for the Dire Wolf modem path;
- `n0jcg-winlink-rms.service` for LinBPQ and the RMS application.

### LAN Winlink Post Office

The optional Network Post Office uses TCP port 8772 and does not key the radio.
Enable it in the protected Winlink environment, regenerate the configuration,
and restart LinBPQ. In Winlink Express choose **Network Post Office**, enter
the ROC host and port 8772, and enable sending from the Outbox. Complete the
user's operator name and CMS credentials in LinBPQ Mail Management before
relying on automated CMS polling.

## 10. Protected operator controls

Configure the administrator password from a local terminal or SSH session:

```bash
cd /home/n0jcg/sdrdev/N0JCG-ROC
sudo deploy/configure_operator_controls.sh
```

The password must contain at least 10 characters. The script stores a salted
PBKDF2-SHA256 record and a random session-signing secret, not the plaintext
password. Existing browser sessions are invalidated whenever the password is
changed.

After login, the dashboard can:

- restart the Winlink RMS and modem services;
- enter or leave Winlink maintenance mode;
- test the network-only CMS connection when no RF link is active; and
- download privacy-safe diagnostics.

Administrator sessions expire after 30 minutes. The controls intentionally do
not provide a command shell, arbitrary service names, or an RF test button.

## 11. Routine operation

At the start of an operating period:

1. Confirm the dashboard health label is operational.
2. Check that expected services are active and application links are reachable.
3. Review APRS and Winlink last-activity timestamps.
4. Confirm Weather observations are current.
5. Investigate failed Winlink sessions and abnormal service restarts.

Before planned maintenance, use Winlink maintenance mode or stop the affected
service. Avoid testing CMS connectivity during an active RF transfer.

## 12. Troubleshooting

### Dashboard unavailable

```bash
systemctl status n0jcg-roc.service --no-pager
journalctl -u n0jcg-roc.service -n 50 --no-pager
curl -fsS http://127.0.0.1/api/health
```

Confirm the host address and local firewall. The default dashboard port is 80.

### APRS service active but no frames

- Confirm the expected RTL serial is present with `rtl_test`.
- Confirm no other process owns the SDR.
- Review `journalctl -u n0jcg-aprs-rx.service`.
- Inspect the bounded diagnostic WAV produced by the listener when enabled.
- Verify frequency, mode, gain, antenna, and feedline before changing decoder
  parameters.

### APRS frames appear but the map is empty

Check the map endpoint and the ROC service journal access:

```bash
curl -s http://127.0.0.1/api/aprs-map
systemctl show n0jcg-roc.service -p SupplementaryGroups
journalctl -u n0jcg-aprs-rx.service --since=-24h --no-pager -n 20
```

The endpoint should report `activity_source` as `systemd-journal` and show a
nonzero `callsign_count` when locally decoded frames are available. If the
source is `systemd-journal-unavailable`, reinstall or add
`SupplementaryGroups=systemd-journal` to the `[Service]` section of
`n0jcg-roc.service`, then run `sudo systemctl daemon-reload` and
`sudo systemctl restart n0jcg-roc.service`. Large journal histories may take
up to 30 seconds to scan. A callsign must be heard locally within the 24-hour
window before the map requests its position from aprs.fi.

### Winlink connection fails

- Review both Winlink service journals.
- Confirm radio volume, DigiRig capture level, PTT, narrow/wide mode, and
  coordinated frequency.
- Check current RF-link state before running a CMS test.
- Use a smaller message to separate link setup from long-transfer reliability.

### Weather data stale

- Ping the GW1100 from the ROC.
- Confirm its address in `/etc/n0jcg/weather.env`.
- Check that the gateway and ROC clocks are synchronized.
- Review the collector journal for HTTP timeouts or missing fields.

## 13. Backup, update, and recovery

Back up these local locations before an upgrade:

- `/etc/n0jcg/` for protected service configuration;
- `/var/lib/n0jcg-roc/` for ROC settings, registration, and audit data; and
- `/var/lib/n0jcg-winlink/` for LinBPQ and BPQMail state.

Do not overwrite these directories with files from a release archive. Validate
a new release before restarting services. Preserve the previous archive and a
copy of the service configuration so the installation can be rolled back.

To collect a support snapshot, use the authenticated diagnostics control or
run the read-only status and journal commands in this guide. Remove callsigns,
addresses, message metadata, and network details before sharing a diagnostic
outside the station team.

## 14. Release verification and support

Compare the downloaded archive with `SHA256SUMS.txt` before installation. The
release is published from the `main` branch at:

`https://github.com/bakstaaj/N0JCG-ROC`

When reporting an issue, include the release version, Ubuntu version, affected
service, relevant redacted journal lines, hardware model, and the exact
expected versus observed behavior. Never include passwords, passcodes, license
serials, private keys, or message contents.

---

> **N0JCG Open Radio Platform** — Open radio systems, engineered as one platform.
