# APRS receive-only milestone

The repository now carries the Phase 1 APRS receive-only configuration
contract at `config/direwolf.aprs-rx.example.conf`. It is not installed as a
service and does not contact APRS-IS or key a radio.

The RTL dongle is the APRS receiver. The DigiRig USB audio interface is reserved
for the future Winlink/packet-radio path. The planned receive pipeline is:

```bash
rtl_fm -d 0 -f 144390000 -M fm -s 240000 -r 48000 -g 0 - \
  | direwolf -r 48000 -c config/direwolf.aprs-rx.example.conf -
```

The RTL EEPROM serial (`00014439`) must be resolved before replacing `-d 0`
with a persistent device-selection rule. Linux device indexes are observations,
not identities. The pipeline feeds Dire Wolf through stdin and exposes only the
configured local AGW/KISS listener ports (`18000`/`18001`); it does not use the
DigiRig audio card or transmit.

Before any future local test:

1. Run `tools/server_preflight.sh` and `tools/hardware_ownership_preflight.sh`.
2. Run `tools/hardware_receive_preflight.sh`.
3. Confirm no other receiver process owns the RTL-SDR and that no modem process
   is already using the DigiRig audio device.
4. Start only a supervised, receive-only Direwolf process with this profile.

APRS-IS uplink, digipeating, beacons, PTT, and Winlink remain disabled until
their own safety and coordination checks are complete.

## Diagnostic audio capture

The listener can retain a bounded rolling capture while forwarding the same
audio to Dire Wolf. The deployed service keeps the most recent 60 seconds in
`runtime/aprs/audio-ring.wav`; this helps check whether AFSK audio is arriving
when a packet is not decoded. It does not transmit or change the receive
frequency. Set `APRS_AUDIO_CAPTURE=0` to disable it.
