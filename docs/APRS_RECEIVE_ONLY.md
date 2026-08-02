# APRS receive-only milestone

The repository now carries the Phase 1 APRS receive-only configuration
contract at `config/direwolf.aprs-rx.example.conf`. It is not installed as a
service and does not contact APRS-IS or key a radio.

The profile uses the DigiRig USB audio card by its stable ALSA name:
`plughw:CARD=Device,DEV=0`. ALSA card numbers are intentionally not used because
they can change across reboots. The planned RF receive target is 144.390 MHz;
frequency selection and verification remain a separate hardware-control step.

Before any future local test:

1. Run `tools/server_preflight.sh` and `tools/hardware_ownership_preflight.sh`.
2. Run `tools/hardware_receive_preflight.sh`.
3. Confirm the receiver—not Direwolf—owns the RTL-SDR and that no modem process
   is already using the DigiRig audio device.
4. Start only a supervised, receive-only Direwolf process with this profile.

APRS-IS uplink, digipeating, beacons, PTT, and Winlink remain disabled until
their own safety and coordination checks are complete.
