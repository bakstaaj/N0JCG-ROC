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

## Automatic recovery

The deployed watchdog performs a guarded recovery when the listener is faulty
for two consecutive checks (normally two minutes). It restarts only
`n0jcg-aprs-rx.service`, records the recovery in `pipeline-health.json` and
the journal, and enforces a five-minute cooldown. This prevents a transient
file timestamp delay from causing repeated restarts. The behavior is enabled
by default with `APRS_AUTO_RECOVER=1`; the confirmation and cooldown values
are configurable in the monitor service environment.

For an immediate operator repair, log in under **Operator controls** and use
**Repair APRS listener**. The separate **Repair APRS watchdog** action repairs
the monitor itself.

## Drive-test capture

Before a mobile test, run this on the ROC:

```sh
sudo /home/n0jcg/sdrdev/N0JCG-ROC/tools/aprs_drive_test.sh start
```

The listener remains receive-only. The capture records the service journal,
RTL-SDR diagnostics, Dire Wolf audio statistics and decoded frames (including
audio-level lines), plus a bounded ten-minute WAV ring. When the drive is
complete, stop and package the evidence:

```sh
sudo /home/n0jcg/sdrdev/N0JCG-ROC/tools/aprs_drive_test.sh stop
```

The timestamped archive is written under
`/var/lib/n0jcg-roc/aprs-drive-tests/`. Use `status` at any time to confirm
that it is still running. The WAV ring is bounded so a forgotten test cannot
fill the disk; packet records and journal text continue until stopped.
