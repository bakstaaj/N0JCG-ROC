#!/usr/bin/env python3
"""Create reproducible N0JCG Gateway release archives and checksums."""

from __future__ import annotations

import gzip
import hashlib
import shutil
import tarfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
PREFIX = f"N0JCG-ROC-v{VERSION}"
DIST = ROOT / "dist"
PUBLICATIONS = ROOT / "docs" / "publications"
EXCLUDED_PARTS = {".git", ".venv", ".pytest_cache", "__pycache__", "build", "dist", "runtime"}
EXCLUDED_FILES = {".server.env", "station.toml"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def included_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if not path.is_file():
            continue
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.name in EXCLUDED_FILES or path.suffix in EXCLUDED_SUFFIXES:
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.as_posix())


def build_tar(files: list[Path], destination: Path) -> None:
    with destination.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for path in files:
                    relative = path.relative_to(ROOT)
                    info = archive.gettarinfo(str(path), arcname=f"{PREFIX}/{relative.as_posix()}")
                    info.uid = 0
                    info.gid = 0
                    info.uname = "root"
                    info.gname = "root"
                    info.mtime = 0
                    with path.open("rb") as source:
                        archive.addfile(info, source)


def build_zip(files: list[Path], destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(ROOT)
            info = zipfile.ZipInfo(f"{PREFIX}/{relative.as_posix()}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if path.suffix == ".sh" else 0o644) << 16
            archive.writestr(info, path.read_bytes())


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def main() -> None:
    docx = PUBLICATIONS / f"N0JCG_Gateway_End_User_Guide_v{VERSION}.docx"
    pdf = PUBLICATIONS / f"N0JCG_Gateway_End_User_Guide_v{VERSION}.pdf"
    for required in (docx, pdf):
        if not required.is_file():
            raise SystemExit(f"Missing publication: {required}")

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)
    files = included_files()
    tar_path = DIST / f"{PREFIX}.tar.gz"
    zip_path = DIST / f"{PREFIX}.zip"
    build_tar(files, tar_path)
    build_zip(files, zip_path)

    assets = [tar_path, zip_path]
    for publication in (pdf, docx):
        destination = DIST / publication.name
        shutil.copy2(publication, destination)
        assets.append(destination)

    checksums = DIST / "SHA256SUMS.txt"
    checksums.write_text("".join(f"{digest(path)}  {path.name}\n" for path in assets), encoding="utf-8", newline="\n")
    print("\n".join(str(path) for path in [*assets, checksums]))


if __name__ == "__main__":
    main()
