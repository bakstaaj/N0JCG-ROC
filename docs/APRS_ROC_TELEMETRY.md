# ROC APRS telemetry

The optional `n0jcg-aprs-telemetry.service` publishes standard APRS telemetry
for `N0JCG-5` through APRS-IS only. It does not use the DigiRig, PTT, Pluto,
or RF path.

The five analog channels are CPU temperature, CPU utilization, memory use,
decoded RF frames since the previous report, and pipeline health score. The
digital bits report receiver activity, RF decode recency, audio-pipeline
activity, API reachability, and reserved fields. Definitions are sent before
each report as direct APRS telemetry information packets (not addressed APRS
text messages), so aprs.fi and other telemetry indexers can label and graph
the values. The parameter labels follow the APRS101 field-length limits, and
the digital bit meanings are documented here because the protocol provides one
project name rather than eight separate bit labels.

The digital bits are, in order: ROC active, healthy RF decode, pipeline not in
fault, recent RF packet, recent pipeline activity, local API reachable, and two
reserved bits.

Telemetry is disabled by default. Enable it by adding the settings from
`config/aprs-telemetry.env.example` to `/etc/n0jcg/aprs-igate.env`, then restart
the service. The default interval is 30 minutes to avoid unnecessary APRS-IS
traffic.
