#!/usr/bin/env python3
"""Test a local LinBPQ terminal-to-CMS connection without printing secrets."""

from __future__ import annotations

import re
import socket
import sys
import time


CONFIG = "/var/lib/n0jcg-winlink/bpq32.cfg"


def receive_until(sock: socket.socket, needle: bytes, timeout: float) -> bytes:
    deadline = time.monotonic() + timeout
    data = bytearray()
    while time.monotonic() < deadline:
        sock.settimeout(max(0.1, deadline - time.monotonic()))
        try:
            chunk = sock.recv(4096)
        except TimeoutError:
            break
        if not chunk:
            break
        data.extend(chunk)
        if needle.lower() in data.lower():
            break
    return bytes(data)


def main() -> int:
    text = open(CONFIG, encoding="utf-8").read()
    match = re.search(r"^\s*USER=([^,]+),([^,]+),", text, re.MULTILINE)
    if not match:
        print("CMS_TEST_FAILED local management USER record not found")
        return 1
    username, password = (value.strip().strip('"') for value in match.groups())

    with socket.create_connection(("127.0.0.1", 8011), timeout=5) as sock:
        if b"user:" not in receive_until(sock, b"user:", 5).lower():
            print("CMS_TEST_FAILED LinBPQ user prompt missing")
            return 1
        sock.sendall(username.encode("utf-8") + b"\r")
        if b"password:" not in receive_until(sock, b"password:", 5).lower():
            print("CMS_TEST_FAILED LinBPQ password prompt missing")
            return 1
        sock.sendall(password.encode("utf-8") + b"\r")
        login = receive_until(sock, b">", 5)
        if b"Connected to" not in login:
            print("CMS_TEST_FAILED local LinBPQ authentication rejected")
            return 1

        sock.sendall(b"rms\r")
        response = receive_until(sock, b"CMS via", 20)
        lower = response.lower()
        if b"cms via" not in lower and b"connected to cms" not in lower:
            print("CMS_TEST_FAILED CMS session was not established")
            return 1
        sock.sendall(b"b\r")
        print("CMS_TEST_PASSED authenticated CMS session established")
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, UnicodeError) as exc:
        print(f"CMS_TEST_FAILED {type(exc).__name__}")
        raise SystemExit(1) from None
