# ROC server baseline

Observed read-only over SSH on 2026-08-01.

| Item | Observed value |
| --- | --- |
| LAN address | `192.168.68.145/24` |
| Hostname | `n0jcg-roc` |
| Operating system | Ubuntu 24.04.4 LTS Noble |
| Kernel | 6.8.0-136-generic x86-64 |
| Hardware | Lenovo IdeaPad FLEX-14IWL |
| Processor | Intel Pentium 5405U, 2 cores at 2.30 GHz |
| Memory | 31 GiB total, about 30 GiB available during preflight |
| Root storage | 98 GiB total, 83 GiB available during preflight |
| Network | Wi-Fi `wlp2s0` |
| Failed systemd units | 0 |
| Listening services before ROC deployment | SSH on TCP 22 only |

## RF hardware state

The initial check found only the integrated camera and Qualcomm Bluetooth USB
devices. There was no `/dev/serial` inventory, no DigiRig USB audio device, and
no RTL-SDR attached. ALSA utilities, `rtl_test`, `rtl_eeprom`, and Direwolf were
not installed. Python 3.12.3 was present.

This is a clean application baseline, not a completed radio preflight. Re-run
`tools/server_preflight.sh` after connecting each radio interface and SDR.

## Phase 0 deployment

The foundation service was deployed on 2026-08-01:

| Check | Result |
| --- | --- |
| Source directory | `/home/n0jcg/sdrdev/N0JCG-ROC` |
| systemd unit | `n0jcg-roc.service` |
| Enabled at boot | PASS |
| Active after installation | PASS |
| LAN health API | `http://192.168.68.145:8095/api/health` PASS |
| Dashboard | `http://192.168.68.145:8095/` |
| Transmit interlock | LOCKED: operator enable off, coordination unconfirmed, frequency unset |

## Base tooling installation

The development, USB/audio, RTL-SDR, Direwolf, and AX.25 foundation was
installed on 2026-08-01. Validation found every required command, zero failed
systemd units, no active Direwolf service, no attached radio USB hardware, and
an online ROC API with transmit locked. See [BASE_TOOLING.md](BASE_TOOLING.md).

## Installation sequence

1. Deploy this repository to `/home/n0jcg/sdrdev/N0JCG-ROC`.
2. Run `./tools/validate.sh` as `n0jcg`.
3. Run `./tools/server_preflight.sh` and retain the output.
4. Install the system service with `./tools/install_systemd_service.sh`.
5. Confirm `GET /api/health` locally and from another LAN computer.
6. Attach RF devices one at a time and record stable serial ownership before
   installing or enabling radio services.
