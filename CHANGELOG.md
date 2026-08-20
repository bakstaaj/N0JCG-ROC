# Changelog

## 0.1.9 - 2026-08-19

### CWOP configuration

- Made CWOP latitude and longitude free-form inputs without spinner controls.
- Compactly aligned the four CWOP settings on one row on desktop layouts.

## 0.1.8 - 2026-08-19

### CWOP weather upload

- Added an operator-protected CWOP configuration panel for station ID,
  coordinates, enable state, and upload interval.
- Added the APRS-IS-only CWOP uploader and service with fail-closed defaults.
- Added CWOP status to the weather monitor and documented verification through
  FindU/CWOP.

## 0.1.7 - 2026-08-18

### APRS telemetry

- Persisted the telemetry sequence across publisher restarts so aprs.fi does
  not discard samples as out-of-order.

## 0.1.6 - 2026-08-18

### APRS telemetry

- Restored addressed APRS message framing for telemetry definitions while
  retaining direct `T#` data packets.

## 0.1.5 - 2026-08-18

### APRS telemetry

- Constrained `PARM` labels and the `BITS` project name to APRS101 field
  limits so aprs.fi accepts and displays the definitions.

## 0.1.4 - 2026-08-18

### Operator experience

- Simplified the dashboard header to show the canonical **Radio Operations
  Center** title.

## 0.1.3 - 2026-08-18

### APRS telemetry

- Corrected telemetry and definition packets to use the standard direct APRS
  information-field format required by APRS-IS telemetry indexers.

## 0.1.2 - 2026-08-18

Operational release for APRS observability and passive coverage planning.

### APRS

- Added the receive-only digipeater survey to the dashboard and
  `/api/aprs/digipeaters`.
- Added guidance that distinguishes heard digipeater hops from proof of
  digipeater reachability or authorization.
- Added a focused `deploy/install_aprs_digipeater_survey.sh` preflight and
  deployment script.

## 0.1.1 - 2026-08-11

Patch release for the commissioned Winlink RMS gateway.

### Reliability

- Restarts the Dire Wolf Winlink modem after a clean SIGHUP caused by a
  transient DigiRig USB re-enumeration.
- Preserves explicit operator stops while preventing the RMS gateway from
  remaining in a service-fault state after the hardware returns.

## 0.1.0 - 2026-08-10

First packaged N0JCG Gateway release.

### Operator experience

- Added the branded responsive Radio Operations Center dashboard.
- Added configurable station identity and independent Air Traffic Center and
  Scanner connections.
- Added product registration, five-minute evaluation behavior, and licensed
  continuous operation.
- Added protected operator controls, audit logging, maintenance mode, CMS
  connection testing, and privacy-safe diagnostics.

### APRS and weather

- Added the RTL-SDR/Dire Wolf receive path and receive-only APRS-IS iGate.
- Added timestamped, sortable, pageable APRS frame history.
- Added the optional aprs.fi activity map with current APRS symbols and a
  24-hour heard-station window.
- Added Ecowitt GW1100/WS90 weather collection, pressure, wind, rain, solar,
  and environmental status.

### Winlink

- Added LinBPQ and Dire Wolf RMS Packet service configuration.
- Added RMS identity, channel, service, session history, throughput,
  reliability, and current-link monitoring.
- Added LAN Network Post Office support for Winlink Express.
- Added BPQMail Pending, Delivered, Received, and Archived counters.

### Packaging

- Removed embedded copies of the Air Traffic Center and Scanner applications.
- Added externally safe configuration examples, a branded End User Guide, and
  reproducible ZIP/tar.gz release packaging with SHA-256 checksums.
## APRS operations observability

- Added packet-quality metrics for RF frames, unique stations, duplicates, and
  Dire Wolf decode-confidence samples.
- Added APRS-IS connection/authentication evidence and bounded hourly RF survey
  history to the APRS API and dashboard.
- Expanded the receive-only pipeline watchdog to report RTL/USB errors and
  optionally send state-transition email alerts.
- Added manifest-validated APRS configuration export/import tooling.
