# VARA FM commissioning

N0JCG ROC now supports an optional VARA FM channel alongside the existing
Dire Wolf 1200-baud Packet channel. VARA FM is a Windows modem and runs under
Wine on the supported Ubuntu x86-64 ROC host. The default is disabled.

## Important channel decision

Do not add VARA FM to the existing popular 1200-baud packet frequency without
coordination. VARA FM detects packet activity, but packet stations may not
detect VARA FM transmissions. Use a coordinated channel and publish both
services only after the local amateur-radio coordination decision is complete.

## Software staging

Install the baseline packages and place the current VARA FM installer output at
the path selected in `/etc/n0jcg/winlink-rms.env`:

```bash
sudo apt-get install wine xvfb
sudo install -d -o root -g root -m 0755 /opt/n0jcg/vara-fm
# Install VARA FM into /opt/n0jcg/vara-fm with Wine, then confirm:
sudo test -f /opt/n0jcg/vara-fm/VARAFM.exe
```

Copy the protected Winlink environment file if it does not already exist and
set these values. Keep `VARA_FM_ENABLED=0` during software and audio staging:

```text
VARA_FM_ENABLED=0
VARA_FM_EXE=/opt/n0jcg/vara-fm/VARAFM.exe
VARA_FM_WINEPREFIX=/var/lib/n0jcg-vara-fm/wine
VARA_FM_CALL=N0JCG-10
VARA_FM_COMMAND_PORT=8300
VARA_FM_DATA_PORT=8301
VARA_FM_MODE=FM1200
```

Run the normal generator while LinBPQ is stopped:

```bash
sudo systemctl stop n0jcg-winlink-rms.service
sudo deploy/configure_winlink_rms.sh
```

With VARA disabled, the generated LinBPQ config remains Packet-only. Set
`VARA_FM_ENABLED=1` only after the gates below, rerun the generator, and then
inspect `/var/lib/n0jcg-winlink/bpq32.cfg` for port 3.

## VARA FM settings

Start the modem once as the `n0jcg` service account and configure its own
settings, then stop it before changing the environment file:

- command TCP port: `8300`;
- data TCP port: `8301`;
- FM system: `1200` for a narrow-FM 1200-pin/audio path, or `9600` only when
  the radio and coordinated channel support the wider data path;
- callsign: the configured VARA FM gateway call;
- sound-card input and output: the DigiRig USB audio device;
- PTT: the validated DigiRig PTT method, with transmit disabled during setup.

LinBPQ owns the VARA port and uses `INTERLOCK=1` with the existing Dire Wolf
port. The LinBPQ VARA driver connects to the local command port; VARA's data
port is configured inside VARA FM and is not a second LinBPQ listener.

## RF gates before enabling

1. Confirm VARA FM is authorized for a separate, coordinated channel.
2. Confirm the radio is narrow FM for `FM1200`, with CTCSS/DCS disabled unless
   the coordination plan explicitly requires it.
3. Verify USB audio playback/recording and receive decoding without PTT.
4. Verify PTT release with a dummy load or controlled attenuated test path.
5. Set VARA drive conservatively and verify clean deviation/no clipping.
6. Prove one local VARA FM connect to the gateway callsign.
7. Verify a Winlink CMS session and a `VARAFM1200` channel report.
8. Only then set `VARA_FM_ENABLED=1`, regenerate the config, and enable the
   RMS service.

The VARA process service is installed and enabled by the deployment playbook,
but it exits immediately while `VARA_FM_ENABLED=0`. No RF service is started
by the configuration generator, and `WINLINK_PTT_ENABLED` remains a separate
Dire Wolf safety gate.

## Checks and rollback

```bash
systemctl status n0jcg-vara-fm.service --no-pager
journalctl -u n0jcg-vara-fm.service -n 50 --no-pager
ss -ltnp | grep -E ':8300|:8301'
grep -n -A14 -B2 'ID=VARA FM' /var/lib/n0jcg-winlink/bpq32.cfg
```

If the modem or audio path is unstable, set `VARA_FM_ENABLED=0`, regenerate
the LinBPQ config, and restart `n0jcg-winlink-rms.service`. The existing Packet
path remains available, subject to its own PTT and RF state.
