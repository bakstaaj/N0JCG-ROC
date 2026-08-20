# APRS operations and recovery

The ROC exposes three operational views under **APRS**:

- **Pipeline health** distinguishes a running systemd unit from a working RTL
  audio/Dire Wolf path. It reports stale audio, missing RF decodes, RTL USB
  errors, and the last pipeline activity.
- **Packet quality** reports RF frames, Internet-only frames, unique stations,
  duplicate rate, and Dire Wolf decode-confidence samples when available.
- **APRS-IS health** reports the last observed server, verified login evidence,
  reconnects, failures, and the last locally recorded Internet upload.

RF survey history is retained in hourly buckets for 168 hours under the runtime
directory. It is receive-only evidence; it never enables digipeating or RF
transmit.

## Alerts

The monitor logs state transitions to journald. To enable optional email alerts,
add a systemd drop-in with `APRS_ALERT_EMAIL`, then reload and restart
`n0jcg-aprs-monitor.service`. Alerts are sent only when the state changes, so a
persistent fault does not generate a message every minute.

## Configuration backup

Export the known APRS settings without secrets:

```text
python3 tools/aprs_config_backup.py export /var/backups/n0jcg-aprs-config.tar.gz
```

Include protected APRS-IS credentials only when the backup is stored securely:

```text
python3 tools/aprs_config_backup.py export /var/backups/n0jcg-aprs-config-secrets.tar.gz --include-secrets
```

Restore is manifest-validated and writes only the known station, Dire Wolf,
iGate, telemetry, and serial-number paths:

```text
python3 tools/aprs_config_backup.py import /var/backups/n0jcg-aprs-config.tar.gz
```

After a restore, review the files and restart the affected services. A restore
does not change RF frequency, enable transmit, or enable digipeating.
