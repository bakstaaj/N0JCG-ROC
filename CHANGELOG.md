# Changelog

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
