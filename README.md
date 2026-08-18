# N0JCG Gateway

N0JCG Gateway is a Linux-based Radio Operations Center for Amateur Radio and
station monitoring. Its browser dashboard brings APRS, Winlink RMS Packet,
local weather, system health, and links to independently deployed N0JCG
applications into one operator view.

Version **0.1.3** is the current packaged release. It includes:

- an RTL-SDR APRS receiver and receive-only APRS-IS iGate path;
- APRS frame history, station symbols, and an optional aprs.fi activity map;
- a 1200-baud Winlink RMS Packet gateway with LinBPQ/Dire Wolf integration;
- an optional VARA FM Winlink channel under Wine, interlocked with Packet;
- a LAN Winlink Post Office for Winlink Express;
- Ecowitt GW1100/WS90 weather monitoring;
- authenticated, audited operator controls without browser RF-test controls;
- configurable periodic operator reports sent from `ROC@n0jcg.com`;
- independent application links and read-only health summaries for N0JCG Air
  Traffic Center and N0JCG Scanner;
- five-minute evaluation operation and Gateway license activation; and
- a responsive, branded operator dashboard served directly by the ROC.

## Documentation

- [End User Guide](docs/N0JCG_Gateway_End_User_Guide_v0.1.1.md)
- [Winlink RMS commissioning](docs/WINLINK_RMS_COMMISSIONING.md)
- [VARA FM commissioning](docs/VARA_FM_COMMISSIONING.md)
- [Protected operator controls](docs/OPERATOR_CONTROLS.md)
- [Operator operations reports](docs/ADMIN_REPORTS.md)
- [APRS receive-only setup](docs/APRS_RECEIVE_ONLY.md)
- [Development and deployment playbook](DEVELOPMENT_DEPLOYMENT_PLAYBOOK.md)

The GitHub release also provides a branded PDF guide, editable DOCX guide,
release archives, and SHA-256 checksums.

## Platform and installation model

The supported host is Ubuntu 24.04 LTS on x86-64 with the project installed at:

```text
/home/n0jcg/sdrdev/N0JCG-ROC
```

The dashboard service uses only the Python standard library. Radio and gateway
features additionally use the packages declared in `config/base-packages.txt`,
including Dire Wolf, RTL-SDR utilities, ALSA tools, SoX, and LinBPQ.

For a fresh appliance, follow the End User Guide. Existing development hosts
can validate and install the dashboard with:

```bash
cd /home/n0jcg/sdrdev/N0JCG-ROC
./tools/validate.sh
./tools/install_systemd_service.sh
```

The dashboard is then available at `http://ROC_IP/`. Configuration containing
credentials belongs under `/etc/n0jcg/`; mutable application state belongs
under `/var/lib/n0jcg-roc/`. Neither location is part of the release archive.

## Interactive Wi-Fi setup

On an installed ROC, scan visible networks without changing configuration:

```bash
cd /home/n0jcg/sdrdev/N0JCG-ROC
sudo tools/configure_wifi.sh --scan-only
```

To select an SSID by number and configure it through Netplan:

```bash
sudo tools/configure_wifi.sh
```

The utility removes duplicate SSIDs, hides and confirms the password, validates
the staged Netplan configuration, keeps Wi-Fi at route metric 600, creates a
timestamped backup under `/var/backups/`, and automatically restores that
backup if the selected Wi-Fi network cannot be confirmed.

## Independent operational applications

N0JCG Air Traffic Center and N0JCG Scanner remain in their own repositories and
run independently. The ROC stores an enable switch, host, and port for each
application, creates direct launch links, and reads their health APIs when
enabled. Their source code is intentionally not duplicated here.

## Safety and privacy

The operator is responsible for licensing, station identification, frequency
coordination, RF exposure, radio configuration, and compliance with local
regulations. A Winlink authorization does not assign a frequency.

The dashboard does not provide a general command shell or an RF test-transmit
button. Credentials, APRS-IS passcodes, CMS passwords, exact private location,
and administrator secrets must never be committed. Example files contain
placeholders and should be copied to the protected runtime locations described
in the guide.

## Development validation

Development follows [DEVELOPMENT_DEPLOYMENT_PLAYBOOK.md](DEVELOPMENT_DEPLOYMENT_PLAYBOOK.md).
Before committing or packaging, run:

```bash
make test
./deploy/deploy.sh --check-only
```

The repository hygiene check rejects tracked private configuration, private-key
material, token-like GitHub credentials, CRLF source files, and whitespace
errors.
