#!/usr/bin/env python3
"""Issue a bounded DigiRig RTS PTT pulse for dummy-load commissioning."""

from __future__ import annotations

import argparse
import array
import fcntl
import os
import termios
import time


DEFAULT_DEVICE = (
    "/dev/serial/by-id/"
    "usb-Silicon_Labs_CP2102N_USB_to_UART_Bridge_Controller_"
    "30217bb31dc6ef11ba3469527a5e3baa-if00-port0"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default=DEFAULT_DEVICE)
    parser.add_argument("--duration", type=float, default=0.75)
    parser.add_argument("--confirm-dummy-load", action="store_true")
    args = parser.parse_args()

    if not args.confirm_dummy_load:
        parser.error("--confirm-dummy-load is required")
    if not 0.1 <= args.duration <= 2.0:
        parser.error("duration must be between 0.1 and 2.0 seconds")

    fd = os.open(args.device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    rts = array.array("i", [termios.TIOCM_RTS])
    try:
        fcntl.ioctl(fd, termios.TIOCMBIS, rts)
        print(f"PTT_ASSERTED duration={args.duration:.2f}s", flush=True)
        time.sleep(args.duration)
    finally:
        fcntl.ioctl(fd, termios.TIOCMBIC, rts)
        os.close(fd)
        print("PTT_RELEASED", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
