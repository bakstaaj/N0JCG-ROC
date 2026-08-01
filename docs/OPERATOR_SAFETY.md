# Operator safety and commissioning

## Before connecting transmit-capable hardware

- Confirm the AT-778UV microphone/PTT cable pinout for the exact radio.
- Confirm DigiRig audio devices and the CP210x serial interface independently.
- Prove which process owns the serial port before enabling RTS PTT.
- Disable VOX, DTR PTT, and CAT PTT unless the selected modem path requires it.
- Use one owner for the DigiRig serial/PTT line at a time.
- Set a transmit timeout and begin with minimum practical power.
- Use a dummy load for audio/PTT timing tests that do not require an over-air peer.

## Gateway frequency rule

`144.900-145.100 MHz` is only a planning range from the earlier Colorado band
plan research. It is not an assigned N0JCG gateway channel. The production
frequency remains unset until the current RMS inventory, local activity survey,
and human coordination are complete.

## Private station data

Keep the street address, exact coordinates, credentials, APRS-IS passcode, and
remote-access secrets in untracked local configuration. Operator-facing maps may
use reduced precision when exact placement is unnecessary.
