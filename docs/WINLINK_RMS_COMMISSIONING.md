# Winlink RMS commissioning

The Winlink team authorized the N0JCG gateway on 2026-08-10. Authorization does
not select an RF channel or prove the transmit path.

## Proven baseline

- AnyTone AT-778UV receive audio through DigiRig Mobile decodes 1200-baud AX.25.
- Radio volume 10 and DigiRig capture 26 percent (-3 dB), with AGC off, are the
  current receive calibration.
- LinBPQ 6.0.25.18 is installed from the pinned upstream binary.
- The end-to-end DigiRig, AnyTone, attenuated RF, RTL-SDR, and Dire Wolf path
  decoded a controlled packet before the antenna was installed.
- The production services are enabled and Winlink accepted the N0JCG-10 channel
  report for 145.070 MHz, 1200-baud packet.

## Required station data

Copy `config/winlink-rms.env.example` to `/etc/n0jcg/winlink-rms.env`, protect it
with mode 0600, and fill in the RMS password, a unique local management password,
the coordinated frequency, service hours, transmitter power, antenna height
above local ground in feet, antenna gain, and antenna direction. Do not put
those passwords in Git.

Generate the runtime files with:

```bash
sudo deploy/configure_winlink_rms.sh
```

The generator records the authorization and creates the LinBPQ and Dire Wolf
runtime files, but does not enable or start either service. PTT remains disabled
unless `WINLINK_PTT_ENABLED=1` is explicitly selected.

## Remaining RF gates

1. Confirm the locally coordinated 2-meter packet frequency.
2. Tune the radio, disable CTCSS/DCS, use narrow FM, and open receive squelch.
3. Connect a dummy load or controlled attenuated test path.
4. Verify RTS PTT keys and releases the AnyTone reliably.
5. Calibrate transmit audio for clean 1200/2200 Hz AFSK with no clipping.
6. Prove a local AX.25 connect to `N0JCG-10`.
7. Verify CMS connectivity and the WL2K channel report.
8. Only then enable the services for unattended operation.

## LAN Telnet Post Office

The optional Post Office lets Winlink Express exchange B2F mail with the ROC on
the local network. LinBPQ stores the messages in BPQMail and forwards them to
the CMS through its existing authenticated Telnet port. This path does not use
or key the AnyTone.

Enable these protected settings in `/etc/n0jcg/winlink-rms.env`:

```text
WINLINK_POST_OFFICE_ENABLED=1
WINLINK_POST_OFFICE_CALL=N0JCG-11
```

Run `sudo deploy/configure_winlink_rms.sh` while the LinBPQ service is stopped,
then restart `n0jcg-winlink-rms.service`. When enabled, the generated
configuration starts BPQMail, maps application 2 to the BBS, and publishes the
RMS Relay-compatible Post Office endpoint on TCP port 8772. SMTP, POP3, NNTP,
anonymous access, and bulletin forwarding remain disabled.

The RF RMS application is published as `N0JCG-10` with the node alias `N0RMS`
and quality 255 so a direct AX.25 connect is handed immediately to the CMS
application rather than remaining as an unattached level-2 node link.
The underlying LinBPQ node uses the separate call `N0JCG-15` (`N0ROC`) so a
local operator station using `N0JCG` never duplicates the node identity during
an RF commissioning session.

The current SSID allocation is `N0JCG-10` for the RMS gateway, `N0JCG-11` for
the LAN Post Office, and `N0JCG-15` for the LinBPQ node. Calls `N0JCG-1` and
`N0JCG-2` remain reserved for mobile radios, while `N0JCG-9` remains reserved
for the iPhone/APRS.fi client. The configuration generator rejects reuse of
those three reserved client calls by a ROC Winlink service.

In Winlink Express select **Network Post Office**, add server `N0JCG ROC` at
`192.168.68.114:8772`, and enable **Send all messages in Outbox**. The first B2F
connection creates the Winlink Express user record. In LinBPQ Mail Management,
confirm that the user is marked **RMS Express User**, enable CMS polling for the
base call, and enter that user's operator name and CMS password before treating
receive polling as commissioned. A populated operator name prevents the
interactive `Please enter your Name` prompt from interrupting automated Network
Post Office sessions.
