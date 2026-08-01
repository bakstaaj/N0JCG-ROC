# Architecture

## Operating model

N0JCG-ROC is the control, presentation, history, and planning layer. RF-facing
work stays on a dedicated edge node when that keeps SDRs close to antennas,
preserves proven hardware operation, or isolates receivers from Winlink
transmit energy.

```text
PI-AIR-TRAFFIC-TRACKER ─┐
PI-SCANNER             ─┼─ node APIs/events ─> N0JCG-ROC ─> browser dashboard
APRS RTL-SDR node      ─┤                         │
Winlink radio node     ─┘                         └─ history / planning / health
```

## Ownership boundaries

| Component | Owns | Does not own |
| --- | --- | --- |
| RF edge node | USB device, tuning, demodulation/decoding, local buffering | Unified UI, long-term history, cross-service policy |
| N0JCG-ROC | Dashboard, configuration intent, service health, history, planning | Directly claiming every remote USB device |
| Winlink node | DigiRig audio/PTT, AT-778UV, Direwolf/RMS services | APRS channel monitoring |
| APRS node | RTL-SDR, 144.390 MHz receive, Direwolf, APRS-IS uplink | RF transmission or digipeating in Phase 1 |

All USB receivers will be assigned by stable EEPROM serial. Linux enumeration
indexes are observations, not identities.

## Safety contract

The ROC must not expose a functional transmit command until all of these are
separately true:

1. The operator explicitly enables transmit.
2. The gateway frequency is configured.
3. Local frequency coordination is recorded as confirmed.
4. Radio, interface, audio level, timeout, and identification checks pass.
5. A controlled low-power or dummy-load validation has been completed where
   the test permits it.

Requested state and observed radio state will be shown separately. A command
acknowledgement alone is not proof that the radio changed state.

## API foundation

The Phase 0 service exposes:

- `GET /api/health`
- `GET /api/station`
- `GET /api/services`
- `GET /api/system`

`/api/system` reports host resources, declared tool availability, and observed
audio/serial/RTL hardware without claiming or configuring any device. Hardware
presence is an inventory observation, not proof that an RF service is ready.
Built-in host sound cards remain visible in the API but do not count as an
attached RF path; only USB audio, stable serial devices, and RTL-SDRs change the
bare-server state.

Future node adapters will normalize each project's existing API rather than
copying its backend into this repository.
