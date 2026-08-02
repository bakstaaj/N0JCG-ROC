# Air Traffic application migration to ROC

The PI Air Traffic Tracker is the source application for the ROC Air Traffic
module. The first migration target is the web/API experience; receiver
ownership moves only after the required SDRs are physically attached and
validated on the ROC server.

## Current source application

| Item | Current value |
|---|---|
| Source checkout | `PI-AIR-TRAFFIC-TRACKER` |
| Pi web port | `8090` |
| ADS-B decoder | app-owned `readsb` |
| UAT decoder | app-owned `dump978-fa`, manually gated |
| UI | `web/index.html`, `web/app.js`, `web/app.css` |
| Backend | `src/backend/pi_air_traffic_backend.py` plus the shared Windows API module |

The PI UI is substantially larger than the current ROC foundation UI, so it
should be mounted as an Air Traffic module rather than replacing the ROC
station shell. Its API routes and static assets should be namespaced or
adapted behind the ROC server.

## Hardware ownership boundary

The ROC currently owns RTL serial `00000144` for receive-only APRS on 144.390
MHz. The Air Traffic application must not claim it. The PI application’s
documented roles are separate receivers:

| Role | EEPROM serial | ROC status |
|---|---|---|
| ADS-B 1090 | `00001090` | Not attached/validated |
| UAT 978 | `00000978` | Not attached/validated |
| NOAA/Airband | `00000162` | Not attached/validated |
| APRS | `00000144` | Active ROC owner |

No decoder migration should be declared complete until serial-first device
resolution, USB ownership, service startup, and API smoke checks pass on the
ROC host.

## Migration sequence

1. Copy and namespace the PI web assets under an ROC Air Traffic module.
2. Port the status/readsb API contract to an ROC backend adapter without
   starting any decoder when its serial is absent.
3. Add ROC service inventory and dashboard health for the Air Traffic module.
4. Attach and identify the ADS-B/UAT/NOAA receivers by EEPROM serial.
5. Install app-owned decoder binaries and validate each receiver independently.
6. Enable live aircraft data and audio only after the APRS RTL ownership check
   remains clean.

Until step 4, the module should report `planned` or `hardware-missing`, not
pretend that the PI’s old aircraft JSON is live ROC data.
