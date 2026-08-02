from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
from urllib.parse import urlparse

from . import __version__
from .config import load_station_config, transmit_interlock
from .inventory import SERVICES
from .system_status import collect_system_status


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WEB_ROOT = PROJECT_ROOT / "web"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "station.toml"
APRS_LOG_PATH = PROJECT_ROOT / "runtime" / "aprs" / "packets.log"
APRS_FRAME_PATTERN = re.compile(r"^(?:\[[^\]]+\]\s*)?[A-Z0-9][A-Z0-9-]{1,8}>[^:]+:.+$")


def parse_aprs_frames(lines: list[str]) -> list[str]:
    return [line.strip() for line in lines if APRS_FRAME_PATTERN.match(line.strip())]


def collect_aprs_status() -> dict:
    try:
        lines = APRS_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    frames = parse_aprs_frames(lines)
    active = False
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            command = (proc / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "ignore")
        except OSError:
            continue
        if "rtl_fm" in command and "00000144" in command:
            active = True
            break
    return {
        "configured": True,
        "active": active,
        "packet_count": len(frames),
        "last_packet": frames[-1] if frames else None,
        "packets": frames[-20:],
        "recent": lines[-20:],
    }


class RocRequestHandler(BaseHTTPRequestHandler):
    server_version = f"N0JCG-ROC/{__version__}"

    def do_GET(self) -> None:  # noqa: N802 - standard library handler API
        route = urlparse(self.path).path
        if route == "/api/health":
            self._json(
                {
                    "status": "ok",
                    "version": __version__,
                    "mode": "phase-0-foundation",
                    "transmit": transmit_interlock(self.server.station_config),
                }
            )
            return
        if route == "/api/station":
            self._json(self.server.station_config)
            return
        if route == "/api/services":
            self._json({"services": SERVICES})
            return
        if route == "/api/system":
            self._json(collect_system_status())
            return
        if route == "/api/aprs":
            self._json(collect_aprs_status())
            return
        self._static(route)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        content = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _static(self, route: str) -> None:
        relative = "index.html" if route == "/" else route.lstrip("/")
        candidate = (self.server.web_root / relative).resolve()
        try:
            candidate.relative_to(self.server.web_root.resolve())
        except ValueError:
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        if not candidate.is_file():
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        content = candidate.read_bytes()
        media_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{media_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


class RocServer(ThreadingHTTPServer):
    web_root: Path
    station_config: dict


def create_server(
    host: str = "127.0.0.1",
    port: int = 8095,
    *,
    web_root: Path = DEFAULT_WEB_ROOT,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> RocServer:
    server = RocServer((host, port), RocRequestHandler)
    server.web_root = web_root
    server.station_config = load_station_config(config_path)
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="N0JCG Radio Operations Center")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8095)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args()
    server = create_server(args.host, args.port, config_path=args.config)
    print(f"N0JCG-ROC {__version__} listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
