# Standalone Air Traffic Center

The N0JCG Air Traffic Center remains a standalone application in the
`PI-AIR-TRAFFIC-TRACKER` repository and runs on the dedicated Pi at:

`http://192.168.68.141:8090/` (current station setting)

The ROC dashboard provides a direct link to that Pi. The ROC does not proxy,
serve, or manage the Air Traffic Center application, receiver services, or
decoder processes. This keeps the Pi usable as a standalone system while the
ROC remains an optional dashboard and control point.

## Ownership boundary

- Air Traffic UI, API, RTL-SDR receivers, `readsb`, `dump978-fa`, and NOAA/
  airband services belong to the dedicated Air Traffic Pi.
- The ROC owns its own dashboard and receive-only APRS services.
- The Air Traffic Pi must not claim the ROC APRS receiver.

## Operations

Open the ROC dashboard and select **Open Air Traffic Center**, or browse
directly to the Pi URL above. Receiver health and Air Traffic API checks are
performed by the Pi's own UI and services.

Change the enabled state, Pi address, or port from the ROC dashboard's
**Application connections** section. The saved setting changes the direct link
and ROC health summary; it does not move or duplicate the Air Traffic code.
