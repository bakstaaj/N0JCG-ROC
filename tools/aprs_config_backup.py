#!/usr/bin/env python3
"""Export/import APRS configuration with an explicit, validated file list.

Secrets are excluded unless --include-secrets is supplied.  Restore never
executes shell content and writes only the known APRS configuration paths.
"""
from __future__ import annotations

import argparse
import json
import os
import tarfile
import tempfile
from pathlib import Path

PROJECT = Path(os.environ.get("N0JCG_ROC_ROOT", Path(__file__).resolve().parents[1]))
FILES = {
    "station.toml": PROJECT / "config" / "station.toml",
    "direwolf.aprs-rx.example.conf": PROJECT / "config" / "direwolf.aprs-rx.example.conf",
    "aprs-igate.env": Path("/etc/n0jcg/aprs-igate.env"),
    "aprs-telemetry.env": Path("/etc/n0jcg/aprs-telemetry.env"),
    "aprs-serial.env": Path("/etc/n0jcg/aprs-serial.env"),
}
SECRET_NAMES = {"aprs-igate.env", "aprs-telemetry.env"}


def archive(destination: Path, include_secrets: bool = False) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    included = []
    with tarfile.open(destination, "w:gz") as output:
        manifest = {"format": 1, "files": []}
        for name, source in FILES.items():
            if name in SECRET_NAMES and not include_secrets:
                continue
            if not source.is_file():
                continue
            output.add(source, arcname=f"config/{name}", recursive=False)
            included.append(name)
            manifest["files"].append(name)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            json.dump(manifest, handle, indent=2)
            manifest_path = Path(handle.name)
        output.add(manifest_path, arcname="manifest.json")
        manifest_path.unlink(missing_ok=True)
    destination.chmod(0o600)
    return {"ok": True, "archive": str(destination), "files": included, "secrets_included": include_secrets}


def restore(source: Path) -> dict:
    if not source.is_file():
        raise ValueError("backup archive does not exist")
    restored = []
    with tarfile.open(source, "r:gz") as archive_file:
        members = {member.name: member for member in archive_file.getmembers()}
        manifest_member = members.get("manifest.json")
        if not manifest_member:
            raise ValueError("backup manifest is missing")
        manifest = json.load(archive_file.extractfile(manifest_member))
        for name in manifest.get("files", []):
            target = FILES.get(name)
            member = members.get(f"config/{name}")
            if not target or not member or not member.isfile():
                raise ValueError(f"invalid backup entry: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            extracted = archive_file.extractfile(member)
            if extracted is None:
                raise ValueError(f"cannot read backup entry: {name}")
            target.write_bytes(extracted.read())
            if name in SECRET_NAMES:
                target.chmod(0o600)
            restored.append(name)
    return {"ok": True, "restored": restored}


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("export")
    make.add_argument("destination", type=Path)
    make.add_argument("--include-secrets", action="store_true")
    load = sub.add_parser("import")
    load.add_argument("archive", type=Path)
    args = parser.parse_args()
    print(json.dumps(archive(args.destination, args.include_secrets) if args.command == "export" else restore(args.archive), indent=2))


if __name__ == "__main__":
    main()
