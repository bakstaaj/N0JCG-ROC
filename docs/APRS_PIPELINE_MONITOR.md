# APRS pipeline monitor

`n0jcg-aprs-monitor.service` runs continuously on the ROC and writes its last
observation to `runtime/aprs/pipeline-health.json`. It also records state
changes in the system journal under `n0jcg-aprs-monitor`.

The dashboard/API reports three independent outcomes:

- **Healthy**: the RTL process is present, the audio ring is advancing, and a
  recent RF frame was decoded.
- **Degraded**: the process and audio path are alive, but RF has been quiet for
  more than six hours. Internet-only iGate beacons do not count as RF frames.
- **Fault**: the RTL process is gone or the audio ring has stopped advancing for
  more than three minutes.

This separation prevents a quiet RF channel from looking like a hardware fault,
while still exposing the failure mode where systemd says “running” but no audio
or RF data is moving. Thresholds can be overridden with
`APRS_PIPELINE_STALE_SECONDS` and `APRS_RF_QUIET_SECONDS` in the service
environment.
