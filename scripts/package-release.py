"""Create a clean, self-contained Windows release without changing the installed app.

Personal data is never copied. Only explicitly recognized program files, a
catalog-verified model, fresh configuration and curated public notices enter ZIP.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from urllib.parse import urlsplit
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))
from hisser.models import MODELS

MAX_FOLDER_BYTES = 4_000_000_000
MAX_ASSET_BYTES = 2 * 1024**3
APPLICATION_ID = "Hisser.LocalTranscriber.1"
MODEL_REVISION = "5359861c739e955e79d9a303bcbc70fb988958b1"
ROOT_PROGRAM_FILES = {
    "base_library.zip", "cudart64_110.dll", "ggml-base.dll", "ggml.dll",
    "libcrypto-3.dll", "libffi-8.dll", "libssl-3.dll", "libtommath.dll",
    "msvcp140.dll", "pyexpat.pyd", "python314.dll", "select.pyd", "tcl90.dll",
    "tcl9tk90.dll", "unicodedata.pyd", "vcomp140.dll", "vcruntime140.dll",
    "vcruntime140_1.dll", "whisper.dll", "zlib1.dll", "_asyncio.pyd",
    "_bz2.pyd", "_ctypes.pyd", "_decimal.pyd", "_elementtree.pyd",
    "_hashlib.pyd", "_lzma.pyd", "_multiprocessing.pyd", "_overlapped.pyd",
    "_queue.pyd", "_socket.pyd", "_ssl.pyd", "_tkinter.pyd", "_uuid.pyd",
    "_wmi.pyd", "_zstd.pyd",
}
CPU_NAMES = {
    "whisper-cli.exe", "whisper.dll", "ggml.dll", "ggml-base.dll",
    "ggml-cpu-x64.dll", "ffmpeg.exe", "ffprobe.exe", "msvcp140.dll",
    "vcruntime140.dll", "vcruntime140_1.dll", "vcomp140.dll",
}
CPU_VARIANTS = {"ggml-cpu-" + cpu + ".dll" for cpu in (
    "alderlake", "cannonlake", "cascadelake", "haswell", "icelake",
    "sandybridge", "skylakex", "sse42", "x64")}
CUDA_NAMES = (CPU_NAMES - {"ffmpeg.exe", "ffprobe.exe"}) | {
    "ggml-cuda.dll", "cublas64_11.dll", "cublaslt64_11.dll", "cudart32_110.dll",
    "cudart64_110.dll", "nvrtc64_112_0.dll", "nvrtc-builtins64_118.dll",
}
REQUIRED_CUDA = CUDA_NAMES - {"cudart32_110.dll"}
ASSETS = {"assets/hisser.ico", "assets/hisser.png", "assets/hisser-64.png"}
EXCLUDED_ASSETS = {"assets/hisser-source.png", "assets/icon-check.png"}
LIBRARY_PATTERN = re.compile(
    r"(?:PIL/_(?:avif|imaging|imagingcms|imagingtk|webp)|"
    r"charset_normalizer/(?:cd|md))\.cp314-win_amd64\.pyd", re.IGNORECASE)
SHA_PATTERN = re.compile(r"[a-f0-9]{64}")
VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+(?:[-.][A-Za-z0-9]+)*")
MSVC_NAMES = {"msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll", "vcomp140.dll"}
LOCAL_PATH_PATTERN = re.compile(
    r"(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/]|(?<![A-Za-z0-9_./:-])/(?:Users|home)/|\\\\[^\s\\]+\\)")


class ReleaseError(ValueError):
    """An input is not safe or complete enough to distribute."""


@dataclass(frozen=True)
class Entry:
    relative: str
    path: Path | None = None
    content: bytes | None = None
    expected_sha256: str | None = None


def assert_plain_path(path: Path) -> None:
    """Reject symlinks and Windows junction/reparse paths, including ancestors."""
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ReleaseError(f"Linked inputs or output paths are not allowed: {part.name}")
        if part.exists() and getattr(part.lstat(), "st_file_attributes", 0) & 0x400:
            raise ReleaseError(f"Reparse inputs or output paths are not allowed: {part.name}")


def safe_relative(relative: str) -> str:
    if not isinstance(relative, str):
        raise ReleaseError("Archive paths must be plain strings")
    path = PurePosixPath(relative)
    if (not relative or "\\" in relative or ":" in relative or path.is_absolute()
            or any(part in ("", ".", "..") or part.rstrip(" .") != part
                   or re.search(r"[\x00-\x1f<>\"|?*]", part)
                   or re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part, re.IGNORECASE)
                   for part in relative.split("/"))):
        raise ReleaseError(f"Unsafe archive entry: {relative!r}")
    return relative


def read_json(path: Path) -> dict:
    assert_plain_path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("expected an object")
        return value
    except (OSError, UnicodeError, ValueError) as exc:
        raise ReleaseError(f"Invalid or missing {path.name}") from exc


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def public_text(path: Path) -> bytes:
    assert_plain_path(path)
    try:
        content = path.read_bytes()
        text = content.decode("utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise ReleaseError(f"Cannot read public notice: {path.name}") from exc
    if LOCAL_PATH_PATTERN.search(text):
        raise ReleaseError(f"Public notice contains a local path: {path.name}")
    return text.encode("utf-8")


def tree_files(root: Path):
    assert_plain_path(root)
    if not root.is_dir():
        raise ReleaseError(f"Required directory is missing: {root.name}")
    for path in sorted(root.rglob("*")):
        assert_plain_path(path)
        if path.is_file():
            if not stat.S_ISREG(path.stat().st_mode):
                raise ReleaseError(f"Only regular files can be packaged: {path.name}")
            yield path


def load_overlay(root: Path | None) -> tuple[dict[str, Entry], list[dict]]:
    if root is None:
        return {}, []
    raw = read_json(root / "provenance.json")
    files = raw.get("files", [])
    components = raw.get("components", [])
    if not isinstance(files, list) or not isinstance(components, list) or not files or not components:
        raise ReleaseError("The redistribution overlay needs public component and file verification records")
    replacements = {}
    for record in files:
        if not isinstance(record, dict):
            raise ReleaseError("Invalid overlay file record")
        relative = safe_relative(record.get("path", ""))
        name = relative.lower()
        allowed = name in CPU_NAMES | CPU_VARIANTS or (name.startswith("cuda/") and name[5:] in CUDA_NAMES | CPU_VARIANTS)
        if not allowed or name in replacements:
            raise ReleaseError("An overlay record targets an unrecognized or duplicate program file")
        digest = record.get("sha256", "")
        size = record.get("size", 0)
        path = root / relative
        assert_plain_path(path)
        if (not isinstance(digest, str) or not SHA_PATTERN.fullmatch(digest)
                or isinstance(size, bool) or not isinstance(size, int) or size <= 0
                or not path.is_file() or path.stat().st_size != size):
            raise ReleaseError(f"The overlay file is missing or invalid: {relative}")
        replacements[name] = Entry(relative, path, expected_sha256=digest)
    sanitized = []
    for component in components:
        if not isinstance(component, dict):
            raise ReleaseError("Invalid public overlay component")
        clean = {}
        for key in ("name", "version", "license", "source_sha256"):
            value = component.get(key, "")
            if (not isinstance(value, str) or not value or len(value) > 200
                    or re.search(r"[\\\x00-\x1f]|[A-Za-z]:/", value)):
                raise ReleaseError(f"Invalid public component {key}")
            if key == "source_sha256" and not SHA_PATTERN.fullmatch(value):
                raise ReleaseError("The component source hash is invalid")
            clean[key] = value
        url = component.get("source_url", "")
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.query:
            raise ReleaseError("Public source URLs must use HTTPS without credentials")
        clean["source_url"] = url
        if "source_hash_kind" in component:
            kind = component["source_hash_kind"]
            if not isinstance(kind, str) or not kind or len(kind) > 200 or re.search(r"[\\\x00-\x1f]|[A-Za-z]:/", kind):
                raise ReleaseError("Invalid public source hash description")
            clean["source_hash_kind"] = kind
        if "source_files" in component:
            source_files = component["source_files"]
            if not isinstance(source_files, list) or not source_files:
                raise ReleaseError("Invalid public source-file list")
            clean["source_files"] = [safe_relative(name) for name in source_files]
        flags = component.get("build_flags", [])
        if (not isinstance(flags, list) or not all(isinstance(flag, str) and len(flag) < 200
                and not re.search(r"[\\\x00-\x1f]|[A-Za-z]:/", flag) for flag in flags)):
            raise ReleaseError("The public build flags are invalid")
        clean["build_flags"] = flags
        sanitized.append(clean)
    listed = {record["path"].casefold() for record in files}
    actual = {path.relative_to(root).as_posix().casefold() for path in tree_files(root)
              if path.name != "provenance.json"}
    if actual != listed:
        raise ReleaseError("The overlay contains files without public verification records")
    return replacements, sanitized


def collect_entries(source: Path, version: str, legal: Path,
                    project: Path = PROJECT, runtime_overlay: Path | None = None,
                    require_redistribution_overlay: bool = False) -> tuple[list[Entry], dict]:
    """Build an explicit file list; no settings, recordings or old data are read."""
    if not VERSION_PATTERN.fullmatch(version):
        raise ReleaseError("Use a plain semantic release version, such as 1.1.0")
    source = Path(source).absolute()
    assert_plain_path(source)
    build = read_json(source / "build-manifest.json")
    if build.get("name") != "Hisser" or build.get("version") != version:
        raise ReleaseError("The requested version does not match the built application")
    backend = build.get("backend")
    if backend not in ("cpu", "cuda"):
        raise ReleaseError("The build has an unrecognized backend")
    exe_sha256 = build.get("exe_sha256", "")
    if not isinstance(exe_sha256, str) or not SHA_PATTERN.fullmatch(exe_sha256):
        raise ReleaseError("The build is missing its executable SHA-256")
    profile_path = source / "data" / "transcription-profile.json"
    profile = read_json(profile_path) if profile_path.exists() else {}
    model_id = profile.get("model_id", "large-v3-q5_0")
    if not isinstance(model_id, str) or model_id not in MODELS:
        raise ReleaseError("The selected model is not in the verified catalog")
    model = MODELS[model_id]
    model_path = source / "data" / "models" / model.filename
    assert_plain_path(model_path)
    if not model_path.is_file() or model_path.stat().st_size != model.size:
        raise ReleaseError("The selected model is missing or has the wrong size")
    selected_metadata = read_json(model_path.with_suffix(".bin.metadata.json"))
    if selected_metadata.get("size") != model.size or selected_metadata.get("sha256") != model.sha256:
        raise ReleaseError("The selected model verification record is invalid")

    entries = [Entry("Hisser.exe", source / "Hisser.exe", expected_sha256=exe_sha256)]
    replacements, components = load_overlay(runtime_overlay)
    if require_redistribution_overlay:
        required_replacements = MSVC_NAMES | {"ffmpeg.exe", "ffprobe.exe"}
        if backend == "cuda":
            required_replacements |= {"cuda/" + name for name in MSVC_NAMES}
        if not required_replacements <= replacements.keys():
            raise ReleaseError("Public packaging requires the complete reviewed FFmpeg and Microsoft redistribution overlay")
    internal_names: set[str] = set()
    runtime_names: set[str] = set()
    for path in tree_files(source / "_internal"):
        relative = safe_relative(path.relative_to(source / "_internal").as_posix())
        lowered = relative.lower()
        if relative in EXCLUDED_ASSETS:
            continue
        if lowered == "runtime/cuda/cudart32_110.dll":
            continue  # The official x64 archive also carries an unused x86 DLL.
        if lowered == "runtime/provenance.json":
            continue  # Original includes local paths and an obsolete comparison model.
        if lowered.startswith("runtime/licenses/"):
            continue  # Use the reviewed legal directory instead of stale local notices.
        if lowered == "runtime/readme.md":
            continue
        allowed = (lowered in ROOT_PROGRAM_FILES or relative in ASSETS
                   or LIBRARY_PATTERN.fullmatch(relative))
        if lowered.startswith("runtime/"):
            name = lowered.removeprefix("runtime/")
            runtime_names.add(name)
            allowed = (name in CPU_NAMES | CPU_VARIANTS | {"languages.json"}
                       or (backend == "cuda" and name.startswith("cuda/")
                           and name[5:] in CUDA_NAMES | CPU_VARIANTS))
        if not allowed:
            raise ReleaseError(f"Unrecognized program file requires review: _internal/{relative}")
        replacement = None
        if lowered.startswith("runtime/"):
            replacement = replacements.get(lowered.removeprefix("runtime/"))
        elif lowered in MSVC_NAMES:
            replacement = replacements.get(lowered)
        entries.append(Entry("_internal/" + relative,
                             replacement.path if replacement else path,
                             expected_sha256=replacement.expected_sha256 if replacement else None))
        internal_names.add(lowered)
    required = {"base_library.zip", "python314.dll", "_tkinter.pyd", "assets/hisser.ico"}
    if not required <= internal_names or not CPU_NAMES <= runtime_names:
        raise ReleaseError("The frozen application or CPU runtime is incomplete")
    if backend == "cuda" and not {"cuda/" + name for name in REQUIRED_CUDA} <= runtime_names:
        raise ReleaseError("The CUDA runtime is incomplete")

    legal_entries = []
    for path in tree_files(legal):
        relative = safe_relative(path.relative_to(legal).as_posix())
        if path.suffix.lower() not in (".txt", ".md", ".json"):
            raise ReleaseError(f"Only reviewed text notices belong in the legal directory: {relative}")
        legal_entries.append(Entry("licenses/" + relative, content=public_text(path)))
    if not legal_entries:
        raise ReleaseError("The reviewed redistribution license directory is empty")
    entries += legal_entries
    for name in ("USER_GUIDE.md", "THIRD_PARTY_NOTICES.md", "docs/DISTRIBUTION.md"):
        entries.append(Entry(name, content=public_text(project / name)))
    if (project / "LICENSE").is_file():
        entries.append(Entry("LICENSE", content=public_text(project / "LICENSE")))
    entries.append(Entry("START HERE.txt", content=(
        "Hisser for Windows (64-bit)\n\n"
        "1. Extract the entire ZIP into a writable folder. Do not run inside ZIP.\n"
        "2. Open the Hisser folder and double-click Hisser.exe.\n"
        "3. Choose an audio or video file, then select Transcribe.\n\n"
        "Keep Hisser.exe, _internal and data together. No Python or installer is needed.\n"
        "Automatic processing tries a compatible NVIDIA GPU and falls back to CPU.\n"
        "The included model works offline. No driver or GPU toolkit is installed.\n"
        "See USER_GUIDE.md for exports, troubleshooting, accuracy and removal.\n"
        "To remove: close Hisser, delete this whole folder and any shortcut you made.\n"
    ).encode("utf-8")))
    model_metadata = {
        "name": model.filename, "model_id": model.id,
        "repository": "ggerganov/whisper.cpp", "revision": MODEL_REVISION,
        "download_url": f"https://huggingface.co/ggerganov/whisper.cpp/resolve/{MODEL_REVISION}/{model.filename}",
        "size": model.size, "sha256": model.sha256, "license": "MIT",
    }
    entries += [
        Entry("data/models/" + model.filename, model_path, expected_sha256=model.sha256),
        Entry("data/models/" + model.filename + ".metadata.json", content=json_bytes(model_metadata)),
        Entry("data/transcription-profile.json", content=json_bytes({"model_id": model.id, "cpu_threads": 6})),
        Entry("portable.json", content=json_bytes({"application_id": APPLICATION_ID, "name": "Hisser",
              "version": version, "portable": True, "data_relative_path": "data"})),
        Entry("build-manifest.json", content=json_bytes({"name": "Hisser", "version": version,
              "exe_sha256": exe_sha256, "portable": True, "backend": backend,
              "model_included": True, "model_id": model.id})),
        Entry("_internal/runtime/provenance.json", content=json_bytes({
            "format_version": 1, "whisper_binary_tag": "b5454", "backend": backend,
            "cuda_version": "11.8" if backend == "cuda" else None,
            "model": model_metadata, "file_hashes": "../../release-manifest.json",
            "notices": "../../licenses/",
            "sources": {
                "whisper": "https://github.com/ggml-org/whisper.cpp/releases/tag/b5454",
                "cuda": "https://developer.download.nvidia.com/compute/cuda/redist/redistrib_11.8.0.json"
                    if backend == "cuda" else None,
            },
            "redistribution_components": components,
        })),
    ]
    names = [safe_relative(entry.relative).casefold() for entry in entries]
    if len(names) != len(set(names)):
        raise ReleaseError("Two files have the same Windows archive name")
    return sorted(entries, key=lambda entry: entry.relative), {"version": version, "backend": backend, "model_id": model.id}


def prepare_release(entries: list[Entry], identity: dict, output: Path) -> dict:
    """Write an inspectable privacy/integrity plan without making a large ZIP."""
    assert_plain_path(output)
    output.mkdir(parents=True, exist_ok=True)
    plan = output / "release-plan.json"
    if plan.exists():
        raise ReleaseError("A release plan already exists; choose a fresh output directory")
    records = []
    total = 0
    for entry in entries:
        safe_relative(entry.relative)
        if entry.path is not None:
            assert_plain_path(entry.path)
            with entry.path.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            size = entry.path.stat().st_size
        else:
            content = entry.content if entry.content is not None else b""
            digest = hashlib.sha256(content).hexdigest()
            size = len(content)
        if entry.expected_sha256 and digest != entry.expected_sha256:
            raise ReleaseError(f"SHA-256 verification failed: {entry.relative}")
        total += size
        records.append({"path": entry.relative, "size": size, "sha256": digest})
    if total >= MAX_FOLDER_BYTES:
        raise ReleaseError("The extracted app exceeds the strict 4 GB storage limit")
    payload = {"format_version": 1, "name": "Hisser", **identity,
               "extracted_bytes_before_manifest": total, "files": records}
    plan.write_bytes(json_bytes(payload))
    return {"plan": str(plan), "extracted_bytes_before_manifest": total, "files": len(records), **identity}


def write_release(entries: list[Entry], identity: dict, output: Path) -> dict:
    """Stream ZIP64; hash the same bytes written, without a second model copy."""
    output = Path(output).absolute()
    assert_plain_path(output)
    version = identity["version"]
    if not VERSION_PATTERN.fullmatch(version):
        raise ReleaseError("Unsafe release version")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"Hisser-{version}-windows-x64.zip"
    checksums = output / (archive.name + ".sha256")
    partial = archive.with_suffix(".zip.part")
    if any(path.exists() for path in (archive, checksums, partial)):
        raise ReleaseError("Release output already exists; choose a fresh output directory")
    records = []
    logical_bytes = 0
    seen = set()
    try:
        with zipfile.ZipFile(partial, "x", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6, allowZip64=True) as target:
            for entry in entries:
                relative = safe_relative(entry.relative)
                if relative.casefold() in seen:
                    raise ReleaseError("Duplicate Windows archive path")
                seen.add(relative.casefold())
                info = zipfile.ZipInfo("Hisser/" + relative, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                digest = hashlib.sha256()
                size = 0
                with target.open(info, "w", force_zip64=True) as destination:
                    if entry.path is not None:
                        assert_plain_path(entry.path)
                        before = entry.path.stat()
                        with entry.path.open("rb") as source:
                            while chunk := source.read(1024 * 1024):
                                destination.write(chunk)
                                digest.update(chunk)
                                size += len(chunk)
                        after = entry.path.stat()
                        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                            raise ReleaseError(f"A program file changed while packaging: {relative}")
                    else:
                        content = entry.content if entry.content is not None else b""
                        destination.write(content)
                        digest.update(content)
                        size = len(content)
                actual = digest.hexdigest()
                if entry.expected_sha256 and actual != entry.expected_sha256:
                    raise ReleaseError(f"SHA-256 verification failed: {relative}")
                logical_bytes += size
                if logical_bytes >= MAX_FOLDER_BYTES:
                    raise ReleaseError("The extracted app exceeds the strict 4 GB storage limit")
                records.append({"path": relative, "size": size, "sha256": actual})
            manifest = json_bytes({"format_version": 1, "name": "Hisser", **identity,
                                   "hash_algorithm": "SHA-256", "files": records})
            logical_bytes += len(manifest)
            if logical_bytes >= MAX_FOLDER_BYTES:
                raise ReleaseError("The extracted app exceeds the strict 4 GB storage limit")
            target.writestr("Hisser/release-manifest.json", manifest)
        if partial.stat().st_size >= MAX_ASSET_BYTES:
            raise ReleaseError("The ZIP exceeds GitHub's strict 2 GiB per-asset limit")
        with partial.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        partial.rename(archive)
        checksums.write_text(f"{digest}  {archive.name}\n", encoding="ascii")
        return {"archive": str(archive), "sha256": digest, "archive_bytes": archive.stat().st_size,
                "extracted_bytes": logical_bytes, "files": len(records) + 1, **identity}
    except BaseException:
        if partial.exists():
            partial.unlink()
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-directory", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, default=PROJECT / "qa" / "release")
    parser.add_argument("--version", required=True)
    parser.add_argument("--legal-directory", type=Path, default=PROJECT / "licenses")
    parser.add_argument("--runtime-overlay", type=Path, required=True,
                        help="Reviewed redistribution runtime replacements")
    parser.add_argument("--prepare-only", action="store_true", help="Write a public file/hash plan without making ZIP")
    args = parser.parse_args()
    try:
        source = args.source_directory.absolute()
        output = args.output_directory.absolute()
        if output == source or output.is_relative_to(source):
            raise ReleaseError("Release output must be outside the source portable app")
        entries, identity = collect_entries(source, args.version, args.legal_directory,
                                            runtime_overlay=args.runtime_overlay,
                                            require_redistribution_overlay=True)
        result = prepare_release(entries, identity, output) if args.prepare_only else write_release(entries, identity, output)
        print(json.dumps(result, indent=2))
    except (ReleaseError, OSError) as exc:
        parser.exit(1, f"Release packaging stopped: {exc}\n")


if __name__ == "__main__":
    main()
