# N0JCG APRS iGate design

This is the authoritative design for the N0JCG ROC APRS receive-only iGate,
including its hardware, software, tuning, diagnostics, and recovery contract.

## Operating contract

- Receive 1200-baud AFSK APRS on 144.390 MHz.
- Decode with Dire Wolf and retain local RF/audio evidence.
- Optionally forward decoded frames to APRS-IS.
- Never transmit, beacon, digipeat, key a radio, or depend on VOX in this path.
- Keep the DigiRig/Winlink RMS audio and PTT path separate.

APRS-IS reception is not proof that the ROC heard a frame; verify the matching
local Dire Wolf record.

## Hardware

```text
2 m antenna -> coax -> RTL-SDR -> ROC Raspberry Pi -> rtl_fm -> Dire Wolf
                                                   -> logs / optional APRS-IS
```

- RTL-SDR: Realtek RTL2838/R820T, EEPROM serial `00014439`. Always select this
  serial, not transient USB device index 0.
- Antenna: approximately 25 ft above the roof line; site elevation about
  9,200–9,225 ft. Use sound coax, connectors, grounding, and clear view.
- The supplied NanoVNA result placed resonance near 146.5 MHz. Retune at
  144.390 MHz; target SWR below 1.5:1 (below 2:1 acceptable).
- Consider a 2 m band-pass filter if strong nearby signals overload the RTL.
- DigiRig belongs to the Winlink/RMS path and is not used by APRS receive.

## RF/audio parameters

The receiver must be tuned to the canonical APRS channel. Start the Blog V4
with zero PPM correction and measure a correction only if a known reference
proves one is needed. The APRS path uses direct tuning with the DC correction
enabled. Do not add `-E offset`: the installed ROC Blog V4 driver rejects
hardware offset-tuning and logs `WARNING: Failed to set offset tuning.` This is
not a 252 kHz frequency correction. The old 144.138 MHz workaround was wrong.

| Parameter | Current value | Purpose |
|---|---:|---|
| RTL serial | `00014439` | Intended receiver |
| `rtl_fm` frequency | `144390000` Hz | Canonical APRS frequency |
| Mode | `fm` | FM demodulation |
| DC correction | `-E dc` | Remove DC offset |
| PPM correction | `-p 0` | Blog V4 starting value; adjust only from measurement |
| Sample rates | `-s 48000 -r 48000` | Dire Wolf audio handoff |
| RTL gain | `20` dB | Current starting field value |

Effective command (intentionally no `-E offset`):

```text
rtl_fm -d 00014439 -f 144390000 -M fm -E dc -p 0 -s 48000 -r 48000 -g 20 -
```

Gain comes from `RTL_GAIN_DB`; an operator drop-in may override the base unit.
Verify the value actually running:

```bash
systemctl show n0jcg-aprs-rx.service -p Environment
pgrep -af rtl_fm
```

Prior 40–49.6 dB tests drove Dire Wolf CH0 levels near 97–98. Around 20 dB
has produced approximately 29–61 on that diagnostic scale. These are audio
levels, not calibrated dBm or S/N. High raw peaks without valid decodes mean
noise or overload; they are not a reason to increase gain.

## Software pipeline

```text
rtl_fm
  -> aprs_audio_capture.py (rolling ring and optional WAV segments)
  -> Dire Wolf (1200 AFSK, stdin audio)
  -> aprs_packet_logger.py (packets.log + packet-records.jsonl)
  -> optional APRS-IS
```

Base Dire Wolf profile (`config/direwolf.aprs-rx.example.conf`):

```text
MYCALL N0JCG-5
CHANNEL 0
MODEM 1200
AGWPORT 18000
KISSPORT 18001
```

The listener adds `ADEVICE null null` because audio arrives on stdin and runs:

```text
direwolf -q h -r 48000 -a 10 -c runtime/aprs/direwolf.conf
```

`-q h` retains heard/audio-level lines; `-a 10` reports audio statistics every
10 seconds. The profile has no PTT, beacon, digipeat, or transmit directives.
Verify effective ports in the live journal because older runs showed both
8001 and 18001 KISS listeners.

### Optional APRS-IS

`/etc/n0jcg/aprs-igate.env` may contain:

```text
APRS_IGATE_ENABLED=1
APRS_IGATE_SERVER=rotate.aprs2.net
APRS_IGATE_PORT=14580
APRS_IGATE_LOGIN=<iGate callsign, normally N0JCG-5>
APRS_IGATE_PASSCODE=<secret passcode>
APRS_IGATE_BEACON_ENABLED=1
APRS_IGATE_BEACON_INTERVAL=30:00
APRS_IGATE_BEACON_COMMENT=N0JCG ROC RX-only iGate 144.390 MHz https://n0jcg.com
```

Never commit the passcode. `qAO`/`qAR` paths describe APRS-IS/iGate routing,
not local RF strength.

## Services and artifacts

- `n0jcg-aprs-rx.service` owns the RTL-to-Dire-Wolf pipeline, runs as `n0jcg`,
  uses `Restart=always`, `RestartSec=5`, `NoNewPrivileges=true`, and
  `PrivateTmp=true`.
- `n0jcg-aprs-monitor.service` checks health and may restart only the APRS
  receive unit.
- `n0jcg-roc.service` serves the operator UI/API. Do not make it depend on the
  receive unit through a helper in a way that creates a systemd cycle.
- `n0jcg-operator-helper.service` must remain ordering-independent from APRS.

| Path | Contents |
|---|---|
| `runtime/aprs/audio-ring.wav` | Bounded rolling signed-16-bit PCM; current window 600 s |
| `runtime/aprs/drive-audio/audio-*.wav` | Sequential one-minute drive-test WAVs |
| `runtime/aprs/rtl.log` | RTL startup, tuner, sample-rate, and errors |
| `runtime/aprs/packets.log` | Dire Wolf decoded/heard output and levels |
| `runtime/aprs/packet-records.jsonl` | Structured decoded frames |
| `runtime/aprs/pipeline-health.json` | Monitor state and timestamps |
| `/var/lib/n0jcg-roc/aprs-drive-tests/` | Completed test archives |

Packet records can contain older entries; correlate only timestamps inside the
test interval. Audio has no source ID, so use distinct callsigns and stagger
two-radio transmissions.

## Health and recovery

| Variable | Value | Meaning |
|---|---:|---|
| `APRS_PIPELINE_STALE_SECONDS` | `180` | Output older than this is stale |
| `APRS_RF_QUIET_SECONDS` | `21600` | Long silence is degraded, not a fault by itself |
| `APRS_AUTO_RECOVER` | `1` | Enable recovery |
| `APRS_AUTO_RECOVER_CONFIRMATIONS` | `2` | Consecutive stale confirmations required |
| `APRS_AUTO_RECOVER_COOLDOWN_SECONDS` | `300` | Minimum recovery interval |
| `APRS_DIREWOLF_AUDIO_STATS_SECONDS` | `10` | Audio-stat interval |

Healthy means the pipeline advances and recent RF decodes exist. Degraded
means the pipeline is alive but RF is quiet. Fault means output is stale or a
process failed. Recovery requires the confirmation and cooldown checks and
restarts only `n0jcg-aprs-rx.service`; it must never restart transmit-capable
Winlink/DigiRig services.

```bash
sudo systemctl status n0jcg-aprs-rx.service -l --no-pager
sudo journalctl -u n0jcg-aprs-rx.service -n 100 --no-pager -o cat
pgrep -af 'rtl_fm|aprs_audio_capture|direwolf'
cat /home/n0jcg/sdrdev/N0JCG-ROC/runtime/aprs/pipeline-health.json
```

Typical failures are RTL ownership conflicts, Dire Wolf usage/configuration
errors, broken pipes after a downstream exit, permissions on a drive directory,
or an incorrectly ordered systemd drop-in.

## Drive-test procedure

```bash
sudo /home/n0jcg/sdrdev/N0JCG-ROC/tools/aprs_drive_test.sh start
sudo /home/n0jcg/sdrdev/N0JCG-ROC/tools/aprs_drive_test.sh status
# transmit known packets while driving or comparing radios
sudo /home/n0jcg/sdrdev/N0JCG-ROC/tools/aprs_drive_test.sh stop
```

`start` creates a timestamped session, clears/uses one-minute WAV segmentation,
and restarts the listener. `stop` collects journals, RTL/Dire Wolf output,
structured records, rolling audio, and all segments into a `.tar.gz` below
`/var/lib/n0jcg-roc/aprs-drive-tests/`.

For every transmission correlate callsign/time, a local packet record, Dire
Wolf level/decode, raw WAV peak/RMS and noise around the packet, and whether the
frame was direct or relayed. Do not use APRS-IS alone to claim ROC coverage.

## Tuning checklist

1. Check antenna, coax, connectors, grounding, polarization, frequency, and
   overload before changing gain.
2. Use `rtl_test -t` only for USB/RTL hardware checks; it is not RF proof.
3. Start at 20 dB and change in small steps through the protected operator
   control. After each change verify `rtl_fm -g` and restart only APRS receive.
4. Treat Dire Wolf `[0.x]` lines and `audio level = ...` as decoder/audio
   diagnostics, not calibrated signal strength.
5. Use a known-good nearby transmitter baseline. A high raw peak without a
   valid packet is noise/overload and should prompt lowering gain or filtering.
6. Measure antenna SWR at 144.390 MHz. A 2:1 mismatch is only about 0.5 dB
   loss, so a large range problem also warrants coax/filter/decoder checks.
7. Archive each gain or antenna change so results are reproducible.

### Frequency and offset guardrail

The only supported APRS frequency is `144390000` Hz. `-p` is RTL crystal
correction in parts per million and should change only from a measured
reference. `-E dc` is the software DC-blocking filter. `-E offset` is a
separate driver/hardware mode and is deliberately not used because this ROC
driver reports it unsupported. A 252 kHz subtraction belongs only to the
legacy Winlink dummy-load capture helper, not APRS reception.

## Deployment and safety

Run the repository tests and shell/Python syntax checks before deployment, then
verify the live service, process ownership, pipeline health, and a real decoded
frame. A passing local test or active systemd unit does not prove RF reception.
Keep APRS-IS passcodes, SSH credentials, and site secrets out of Git. Remove
temporary drive-test drop-ins after testing and reload systemd.
