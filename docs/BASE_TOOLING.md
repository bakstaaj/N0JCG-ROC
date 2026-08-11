# Base radio-development tooling

Installed and validated on `n0jcg-roc` on 2026-08-01 using the package manifest
at `config/base-packages.txt`.

## Installed capabilities

| Area | Packages or commands | Purpose before hardware configuration |
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
- The DigiRig Mobile is detected as a CP2102N serial interface and C-Media USB Audio capture/playback device.
- The RTL dongle is detected as Realtek RTL2838/R820T, EEPROM serial `00014439`.
- `n0jcg` is a member of `dialout` and `audio`; no modem process owns either interface.
- No RTL-SDR is present yet.
- No frequency, modem channel, PTT method, APRS-IS login, or Winlink service
  configuration was created.
- The ROC transmit interlock remains locked.

The commissioned DigiRig receive baseline uses AnyTone volume `10`, C-Media
capture level `26%` (`-3.00 dB`), and USB audio automatic gain control off. An
open-squelch 48 kHz capture measured approximately `-16.4 dBFS` RMS and
`-6.9 dBFS` peak without clipping. Revalidate these levels after changing the
radio volume, DigiRig cable, or USB audio device.

On 2026-08-10, the receive-only commissioning profile decoded an
`N0JCG-2>APBTUV` frame through the AnyTone and DigiRig. Dire Wolf reported 48
kHz input, zero sample errors, and receive audio level 71. The profile had no
PTT configuration and its AGW/KISS listeners were disabled.

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

After each hardware change, run `tools/server_preflight.sh` followed by
`tools/hardware_ownership_preflight.sh`. The current stable serial path is
`/dev/serial/by-id/usb-Silicon_Labs_CP2102N_USB_to_UART_Bridge_Controller_30217bb31dc6ef11ba3469527a5e3baa-if00-port0`.
Do not create a modem or SDR service, or transmit, until the radio profiles and
local frequency coordination are documented. The bounded `rtl_test -t` probe
identified the dongle and restored the kernel driver; its R820T-only result does
not constitute an RF reception test.

For a repeatable receive-only check after reconnecting hardware, run:

```bash
./tools/hardware_receive_preflight.sh
```

It captures two seconds from the DigiRig and a bounded RTL-FM sample, then
removes temporary files. It never configures PTT or starts a persistent service.
