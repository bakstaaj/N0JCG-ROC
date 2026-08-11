# APRS digipeater commissioning

The ROC currently runs an RTL-SDR receive-only iGate on 144.390 MHz. The
digipeater is a separate AnyTone/DigiRig path and must not share its serial/PTT
owner with Winlink or another modem.

## Required gates

1. Confirm the locally coordinated APRS frequency and digipeater identity
   `N0JCG-1`.
2. Identify the DigiRig capture/playback devices and the verified PTT control.
3. Configure one Dire Wolf process as the sole owner of that audio/PTT path.
4. Use minimum practical power, a transmit timeout, and a dummy load first.
5. Start with bounded aliases (`WIDE1-1` and `WIDE2-1`) and monitor for loops.
6. Test with a handheld before enabling unattended operation.

The checked-in profile is a template only. It has no audio device, PTT device,
APRS-IS uplink, beacon, or enabled systemd service until those gates pass.
