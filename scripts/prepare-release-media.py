"""Prepare the pinned public FFmpeg media overlay without executing binaries.

The Microsoft files must come from the licensed hosted-runner REDIST artifact.
The public FFmpeg archive is independently pinned, and only its two reviewed
executables are selected. No settings, models or personal application files are
read or copied by this command.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import stat
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import zipfile


PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "hisser_release_media_packaging", PROJECT / "scripts" / "package-release.py")
release = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release
SPEC.loader.exec_module(release)
DEFAULT_MANIFEST = PROJECT / "runtime" / "distribution-media.json"
CHUNK_BYTES = 1024 * 1024
MAX_ARCHIVE_CONTENT_BYTES = 1_000_000_000
MICROSOFT_COMPONENT = "Microsoft Visual C++ Redistributables"


def sha256(path: Path) -> str:
    release.assert_plain_path(path)
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verified_file(path: Path, record: dict) -> None:
    release.assert_plain_path(path)
    if (not path.is_file() or path.stat().st_size != record["size"]
            or sha256(path) != record["sha256"]):
        raise release.ReleaseError(f"Size or SHA-256 mismatch: {path.name}")


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict:
    manifest = release.read_json(path)
    if manifest.get("format_version") != 1:
        raise release.ReleaseError("Unrecognized public media pin format")
    archive = manifest.get("binary_archive", {})
    url = urlsplit(archive.get("url", ""))
    if (url.scheme != "https" or url.hostname != "github.com"
            or not url.path.startswith("/BtbN/FFmpeg-Builds/releases/download/")
            or url.username or url.password or url.query or url.fragment
            or not release.SHA_PATTERN.fullmatch(archive.get("sha256", ""))
            or type(archive.get("size")) is not int or archive["size"] <= 0):
        raise release.ReleaseError("The public media archive pin is incomplete")
    files = manifest.get("files", [])
    if not isinstance(files, list) or len(files) != 2:
        raise release.ReleaseError("Pin exactly ffmpeg.exe and ffprobe.exe")
    names = set()
    members = set()
    for record in files:
        if not isinstance(record, dict):
            raise release.ReleaseError("Invalid public media file pin")
        name = release.safe_relative(record.get("path", ""))
        member = release.safe_relative(record.get("archive_path", ""))
        if (name not in {"ffmpeg.exe", "ffprobe.exe"} or name in names
                or member.casefold() in members
                or not release.SHA_PATTERN.fullmatch(record.get("sha256", ""))
                or type(record.get("size")) is not int or record["size"] <= 0):
            raise release.ReleaseError("Invalid or duplicate public media file pin")
        names.add(name)
        members.add(member.casefold())
    if not isinstance(manifest.get("components"), list) or not manifest["components"]:
        raise release.ReleaseError("The media source provenance is missing")
    return manifest


def microsoft_inputs(base: Path) -> tuple[dict, dict]:
    """Check every base file, then select just the eight reviewed DLL copies."""
    entries, components = release.load_overlay(base)
    for entry in entries.values():
        if sha256(entry.path) != entry.expected_sha256:
            raise release.ReleaseError(f"Base overlay SHA-256 mismatch: {entry.relative}")
    required = release.MSVC_NAMES | {"cuda/" + name for name in release.MSVC_NAMES}
    if not required <= entries.keys():
        raise release.ReleaseError("The base overlay needs all eight Microsoft DLL copies")
    microsoft = [component for component in components
                 if component["name"] == MICROSOFT_COMPONENT]
    if len(microsoft) != 1:
        raise release.ReleaseError("The base overlay needs one Microsoft REDIST provenance record")
    component = microsoft[0]
    source_files = component.get("source_files", [])
    if (len(source_files) != 4 or set(source_files) != release.MSVC_NAMES
            or component.get("source_hash_kind") !=
            "SHA-256 of the concatenated original DLL bytes in source_files order; not an archive hash"):
        raise release.ReleaseError("The Microsoft original-file hash description is incomplete")
    digest = hashlib.sha256()
    for name in source_files:
        root = entries[name]
        cuda = entries["cuda/" + name]
        if root.expected_sha256 != cuda.expected_sha256:
            raise release.ReleaseError("The Microsoft CPU and CUDA copies differ")
        with root.path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
                digest.update(chunk)
    if digest.hexdigest() != component["source_sha256"]:
        raise release.ReleaseError("The Microsoft original-file aggregate SHA-256 differs")
    return {name: entries[name] for name in sorted(required)}, component


def acquire_archive(manifest: dict, directory: Path) -> Path:
    """Download only the pinned public archive; never replace an existing cache."""
    record = manifest["binary_archive"]
    name = urlsplit(record["url"]).path.rsplit("/", 1)[1]
    release.safe_relative(name)
    release.assert_plain_path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    release.assert_plain_path(target)
    if target.exists():
        verified_file(target, record)
        return target
    partial = directory / (name + ".part")
    release.assert_plain_path(partial)
    if partial.exists():
        raise release.ReleaseError("A partial media download exists; choose a fresh download directory")
    try:
        request = Request(record["url"], headers={"User-Agent": "Hisser-release-preparation"})
        with urlopen(request, timeout=60) as response, partial.open("xb") as destination:
            if urlsplit(response.geturl()).scheme != "https":
                raise release.ReleaseError("The media download redirected away from HTTPS")
            count = 0
            for chunk in iter(lambda: response.read(CHUNK_BYTES), b""):
                count += len(chunk)
                if count > record["size"]:
                    raise release.ReleaseError("The media download exceeds its pinned size")
                destination.write(chunk)
        verified_file(partial, record)
        partial.replace(target)
    except BaseException:
        if partial.is_file():
            partial.unlink()
        raise
    return target


def archive_members(bundle: zipfile.ZipFile, manifest: dict) -> dict:
    """Reject ambiguous or unsafe members even when they would not be selected."""
    actual = {}
    total = 0
    for info in bundle.infolist():
        relative = info.filename[:-1] if info.is_dir() else info.filename
        release.safe_relative(relative)
        key = relative.casefold()
        mode = info.external_attr >> 16
        if key in actual or stat.S_ISLNK(mode):
            raise release.ReleaseError("The media archive contains linked or duplicate paths")
        actual[key] = info
        total += info.file_size
        if total > MAX_ARCHIVE_CONTENT_BYTES:
            raise release.ReleaseError("The media archive expands beyond its allowed size")
    selected = {}
    for record in manifest["files"]:
        info = actual.get(record["archive_path"].casefold())
        if (info is None or info.is_dir() or info.filename != record["archive_path"]
                or info.file_size != record["size"]):
            raise release.ReleaseError("The media archive does not contain the pinned executable")
        selected[record["path"]] = info
    return selected


def prepare(base: Path, output: Path, archive: Path | None = None,
            download_directory: Path | None = None, manifest: dict | None = None) -> dict:
    manifest = load_manifest() if manifest is None else manifest
    base, output = Path(base).absolute(), Path(output).absolute()
    release.assert_plain_path(output)
    if output.exists():
        raise release.ReleaseError("Choose a fresh output directory")
    inputs, microsoft = microsoft_inputs(base)
    if output.resolve().is_relative_to(base.resolve()):
        raise release.ReleaseError("The output must be outside the base overlay")
    if download_directory is not None:
        release.assert_plain_path(download_directory)
        location = download_directory.resolve()
        if location.is_relative_to(base.resolve()) or location.is_relative_to(output.resolve()):
            raise release.ReleaseError("The download cache must be outside the input and output overlays")
    archive = Path(archive).absolute() if archive else acquire_archive(
        manifest, download_directory or PROJECT / "downloads" / "public-media")
    verified_file(archive, manifest["binary_archive"])
    records = []
    # Check the verified ZIP structure before creating any output.
    with zipfile.ZipFile(archive) as bundle:
        selected = archive_members(bundle, manifest)
        for pin in manifest["files"]:
            with bundle.open(selected[pin["path"]]) as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            if digest != pin["sha256"]:
                raise release.ReleaseError(f"Media executable SHA-256 mismatch: {pin['path']}")
        output.mkdir(parents=True)
        for relative, entry in inputs.items():
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(entry.path, target)
            record = {"path": relative, "size": target.stat().st_size,
                      "sha256": entry.expected_sha256}
            verified_file(target, record)
            records.append(record)
        for pin in manifest["files"]:
            target = output / pin["path"]
            with bundle.open(selected[pin["path"]]) as source, target.open("xb") as destination:
                shutil.copyfileobj(source, destination, CHUNK_BYTES)
            verified_file(target, pin)
            records.append({key: pin[key] for key in ("path", "size", "sha256")})
    provenance = {"format_version": 1,
                  "components": [microsoft, *manifest["components"]],
                  "files": sorted(records, key=lambda record: record["path"])}
    (output / "provenance.json").write_bytes(release.json_bytes(provenance))
    # Exercise the same strict inventory/provenance reader used by ZIP packaging.
    release.load_overlay(output)
    return {"format_version": 1, "files": len(records),
            "binary_archive_sha256": manifest["binary_archive"]["sha256"],
            "output_directory": str(output)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-overlay", required=True, type=Path,
                        help="Licensed hosted-runner Microsoft REDIST overlay")
    parser.add_argument("--output-directory", required=True, type=Path,
                        help="Fresh output directory for the public media overlay")
    parser.add_argument("--archive", type=Path, help="Already downloaded pinned BtbN ZIP")
    parser.add_argument("--download-directory", type=Path,
                        help="Archive cache, default downloads/public-media")
    args = parser.parse_args()
    try:
        report = prepare(args.base_overlay, args.output_directory, args.archive,
                         args.download_directory)
    except (release.ReleaseError, OSError, ValueError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"Media preparation failed: {exc}\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
