# Roadmap

## Phase 0 - Foundation (current)

- Project identity and configuration contract.
- Unified dashboard shell.
- Service inventory and health APIs.
- Default-off transmit interlock.
- Automated local smoke tests.
- Live server resource, base-tool readiness, and bare-hardware inventory.

## Phase 1 - Core RF services

- Connect existing ADS-B 1090, UAT 978, NOAA, and Airband node APIs.
- Detect DigiRig audio and serial interfaces without keying the transmitter.
- Resolve every RTL-SDR by EEPROM serial and record service ownership.
- Deploy a receive-only APRS iGate path on 144.390 MHz.
- Add Winlink RMS status after approval and local channel coordination.
- Add system health, logs, Internet status, storage, temperature, and UPS state.

## Phase 2 - Scanner integration

- Connect the existing P25/VHF/UHF scanner as an RF edge node.
- Centralize configuration intent, event history, recordings, and playback.
- Preserve the scanner's coordinated Start/Stop lifecycle.
- Add a packet monitor, packet analyzer, and bounded spectrum views.

## Phase 3 - Gateway planning

- Import the current Winlink RMS channel dataset with source timestamp.
- Plot gateways by mode, frequency, distance, and bearing from the site.
- Add terrain-aware coverage estimates and overlap analysis.
- Survey Colorado packet candidates over multiple days.
- Track occupancy, stations heard, decode quality, and time-of-day patterns.
- Show network opportunities without presenting an algorithmic suggestion as
  frequency coordination approval.

## Deferred until evidence exists

- A production Winlink frequency.
- RF transmit enablement.
- APRS Internet-to-RF gating or digipeating.
- Claims of coverage, receiver sensitivity, or gateway availability.
