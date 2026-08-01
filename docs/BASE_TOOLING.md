# Base radio-development tooling

Installed and validated on `n0jcg-roc` on 2026-08-01 using the package manifest
at `config/base-packages.txt`.

## Installed capabilities

| Area | Packages or commands | Purpose before hardware arrives |
| --- | --- | --- |
| Development | Git, Make, Python 3 venv | Reproducible source validation and isolated future Python tooling |
| Deployment | curl, jq, rsync, lsof, socat | API checks, structured output, synchronization, port and stream diagnostics |
| USB inventory | usbutils, pciutils | Identify buses and device attachment |
| Audio | ALSA utilities, SoX | Enumerate capture/playback devices and perform bounded audio tests |
| SDR | `rtl_test`, `rtl_eeprom`, `librtlsdr` | Identify and validate RTL-SDRs and assign stable EEPROM serials |
| Packet | Direwolf 1.7, libax25, AX.25 tools/apps | Software TNC and AX.25 diagnostics after configuration exists |

Ubuntu installed 42 new packages including dependencies, using approximately
37.9 MB. No reboot was required.

## Deliberately not configured

- Direwolf has no station configuration and is not active.
- No systemd radio service was enabled.
- No ALSA card is present yet.
- No serial/PTT interface is present yet.
- No RTL-SDR is present yet.
- No frequency, modem channel, PTT method, APRS-IS login, or Winlink service
  configuration was created.
- The ROC transmit interlock remains locked.

## Validation

Run on the server:

```bash
cd /home/n0jcg/sdrdev/N0JCG-ROC
./tools/install_base_tools.sh --check-only
./tools/validate_base_tools.sh
```

From the MSYS2 development host:

```bash
cd /home/jim/sdrdev/N0JCG-ROC
./deploy/install_base_tools_remote.sh --check-only
```

When hardware arrives, connect one device at a time and run
`tools/server_preflight.sh` after each attachment. Record stable receiver EEPROM
serials and `/dev/serial/by-id` ownership before creating persistent services.
