# N0JCG Radio Operations Center

N0JCG-ROC is a modular Linux radio-station appliance for N0JCG. It will bring
Winlink, APRS, aircraft tracking, weather, airband, scanners, RF planning, and
system health into one operator dashboard while leaving receiver and radio
hardware ownership with the most appropriate node.

This repository currently contains the **Phase 0 foundation**:

- A zero-dependency Python HTTP/API service.
- A responsive operations-dashboard shell.
- Station and service inventory endpoints.
- An explicit transmit safety interlock, disabled by default.
- Architecture, roadmap, and operator-safety contracts.
- Automated API and static-asset smoke tests.

No radio is keyed, no gateway frequency is selected, and no external network is
contacted by this milestone.

## Initial station identity

| Item | Value |
| --- | --- |
| Project | N0JCG-ROC |
| Operator callsign | `N0JCG` |
| Linux account | `n0jcg` |
| Planned Winlink RMS identity | `N0JCG-10` (approval/configuration pending) |
| Planned APRS RX iGate identity | `N0JCG-5` |
| Site label | Cripple Creek, Colorado |

The private street address and exact coordinates belong in the untracked local
file `config/station.toml`, not in Git.

## Run locally

```bash
cd ~/sdrdev/N0JCG-ROC
cp config/station.example.toml config/station.toml
./tools/dev.sh
```

Open `http://127.0.0.1:8095`.

Run validation with:

```bash
./tools/validate.sh
```

## Validated ROC server

The initial server is `n0jcg-roc` at `192.168.68.145`, running Ubuntu 24.04.4
LTS. After deployment, the LAN dashboard URL is:

```text
http://192.168.68.145:8095
```

See [docs/SERVER_BASELINE.md](docs/SERVER_BASELINE.md) for the observed
hardware/software baseline. Credentials are never stored in this repository.

Development and deployment follow the checked-in
[DEVELOPMENT_DEPLOYMENT_PLAYBOOK.md](DEVELOPMENT_DEPLOYMENT_PLAYBOOK.md). The
base-server radio tools are declared in `config/base-packages.txt` and are
installed only after `./tools/install_base_tools.sh --check-only` passes.
The installed bare-server baseline is documented in
[docs/BASE_TOOLING.md](docs/BASE_TOOLING.md).

## First hardware milestone

The first live milestone will be receive-only station discovery and health:

1. Detect the DigiRig audio and serial/PTT interfaces without transmitting.
2. Inventory RTL-SDR receivers by EEPROM serial rather than Linux device index.
3. Add APRS receive-only monitoring on 144.390 MHz.
4. Survey coordinated packet-channel candidates before configuring RMS transmit.

See [docs/ROADMAP.md](docs/ROADMAP.md) and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
