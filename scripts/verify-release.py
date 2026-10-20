"""Verify a portable release and optionally exercise a freshly extracted copy."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import time
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))
from hisser.models import MODELS, load_profile

_spec = importlib.util.spec_from_file_location("hisser_release_packaging", PROJECT / "scripts/package-release.py")
packaging = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = packaging
_spec.loader.exec_module(packaging)


class VerificationError(ValueError):
    """The candidate is not a verified, clean portable release."""


def file_hash(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _object(content: bytes, label: str) -> dict:
    try:
        payload = json.loads(content)
        if not isinstance(payload, dict):
            raise ValueError("expected object")
        return payload
    except (UnicodeError, ValueError) as exc:
        raise VerificationError(f"Invalid {label}") from exc


def verify_archive(archive: Path, expected_sha256: str,
                   output: Path | None = None) -> dict:
    """Verify exact inventory and every streamed byte before allowing execution."""
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", expected_sha256):
        raise VerificationError("A complete SHA-256 checksum is required")
    packaging.assert_plain_path(archive)
    if archive.stat().st_size >= packaging.MAX_ASSET_BYTES:
        raise VerificationError("The release asset is not below 2 GiB")
    actual_sha256 = file_hash(archive)
    if actual_sha256 != expected_sha256.lower():
        raise VerificationError("The release ZIP SHA-256 does not match")
    if output is not None:
        output = Path(output).absolute()
        packaging.assert_plain_path(output)
        if output.exists():
            raise VerificationError("Extraction requires a fresh output directory")
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        names = set()
        total = 0
        for info in infos:
            packaging.safe_relative(info.filename)
            if (not info.filename.startswith("Hisser/") or info.is_dir()
                    or info.filename.casefold() in names or info.flag_bits & 1):
                raise VerificationError("The ZIP has an unsafe, duplicate, encrypted or extra root entry")
            mode = stat.S_IFMT(info.external_attr >> 16)
            if mode not in (0, stat.S_IFREG):
                raise VerificationError("Linked or special ZIP entries are not allowed")
            names.add(info.filename.casefold())
            total += info.file_size
        if total >= packaging.MAX_FOLDER_BYTES:
            raise VerificationError("The extracted release is not below 4 GB")
        manifest_info = bundle.getinfo("Hisser/release-manifest.json")
        if manifest_info.file_size > 1_000_000:
            raise VerificationError("The release manifest is unexpectedly large")
        manifest = _object(bundle.read(manifest_info), "release manifest")
        if manifest.get("format_version") != 1 or manifest.get("name") != "Hisser" or manifest.get("hash_algorithm") != "SHA-256":
            raise VerificationError("The release manifest has an unsupported format")
        if not isinstance(manifest.get("model_id"), str) or manifest["model_id"] not in MODELS:
            raise VerificationError("The release selects an unrecognized model")
        if not isinstance(manifest.get("version"), str) or not packaging.VERSION_PATTERN.fullmatch(manifest["version"]):
            raise VerificationError("The release has an invalid version")
        if manifest.get("backend") not in ("cpu", "cuda"):
            raise VerificationError("The release has an invalid backend")
        model = MODELS[manifest["model_id"]]
        records = manifest.get("files")
        if not isinstance(records, list) or not records:
            raise VerificationError("The release manifest has no file inventory")
        listed = set()
        records_by_name = {}
        for record in records:
            if not isinstance(record, dict):
                raise VerificationError("Invalid release file record")
            relative = packaging.safe_relative(record.get("path", ""))
            name = "Hisser/" + relative
            if name.casefold() in listed or relative == "release-manifest.json":
                raise VerificationError("Duplicate or recursive manifest record")
            digest = record.get("sha256", "")
            size = record.get("size")
            if (not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
                    or isinstance(size, bool) or not isinstance(size, int) or size < 0):
                raise VerificationError("Invalid release file checksum/size")
            listed.add(name.casefold())
            records_by_name[relative] = record
        if names != listed | {"hisser/release-manifest.json"}:
            raise VerificationError("The ZIP and manifest file inventories differ")
        model_relative = "data/models/" + model.filename
        required = {"Hisser.exe", "LICENSE", "USER_GUIDE.md", "START HERE.txt", "THIRD_PARTY_NOTICES.md",
                    "docs/DISTRIBUTION.md", "portable.json", "build-manifest.json",
                    "data/transcription-profile.json", model_relative,
                    model_relative + ".metadata.json", "_internal/runtime/provenance.json"}
        if not required <= records_by_name.keys() or not any(name.startswith("licenses/") for name in records_by_name):
            raise VerificationError("The clean portable release is incomplete")
        lower_names = {name.lower() for name in records_by_name}
        required_program = {"_internal/base_library.zip", "_internal/python314.dll", "_internal/_tkinter.pyd",
                            "_internal/assets/hisser.ico"} | {"_internal/runtime/" + name for name in packaging.CPU_NAMES}
        if manifest["backend"] == "cuda":
            required_program |= {"_internal/runtime/cuda/" + name for name in packaging.REQUIRED_CUDA}
        if not required_program <= lower_names:
            raise VerificationError("The bundled Python or recognition runtime is incomplete")
        expected_data = {model_relative, model_relative + ".metadata.json", "data/transcription-profile.json"}
        if {name for name in records_by_name if name.startswith("data/")} != expected_data:
            raise VerificationError("The release includes extra data, settings or temporary files")
        if sum(name.lower().endswith(".bin") for name in records_by_name) != 1:
            raise VerificationError("The release must contain exactly one verified model")
        if (records_by_name[model_relative]["sha256"] != model.sha256
                or records_by_name[model_relative]["size"] != model.size):
            raise VerificationError("The model does not match its pinned catalog identity")
        for relative in records_by_name:
            if re.search(r"(?:^|/)(?:\.portable-self-test\.json|settings\.json|.*\.lnk|.*\.log|.*\.wav|.*\.mp4)$", relative, re.I):
                raise VerificationError("Private/runtime-generated material is included in the release")
            allowed = relative in required or relative in expected_data
            if relative.startswith("licenses/"):
                allowed = Path(relative).suffix.lower() in (".md", ".txt", ".json")
            if relative.startswith("_internal/"):
                internal = relative.removeprefix("_internal/")
                lowered = internal.lower()
                allowed = (lowered in packaging.ROOT_PROGRAM_FILES or internal in packaging.ASSETS
                           or packaging.LIBRARY_PATTERN.fullmatch(internal))
                if lowered.startswith("runtime/"):
                    name = lowered.removeprefix("runtime/")
                    allowed = (name in packaging.CPU_NAMES | packaging.CPU_VARIANTS | {"languages.json", "provenance.json"}
                               or manifest["backend"] == "cuda" and name.startswith("cuda/")
                               and name[5:] in (packaging.CUDA_NAMES | packaging.CPU_VARIANTS) - {"cudart32_110.dll"})
            if not allowed:
                raise VerificationError(f"Unrecognized public release file requires review: {relative}")
        if output is not None:
            output.mkdir(parents=True)
        for relative, record in records_by_name.items():
            info = bundle.getinfo("Hisser/" + relative)
            if info.file_size != record["size"]:
                raise VerificationError(f"The archived file size differs: {relative}")
            digest = hashlib.sha256()
            size = 0
            destination = None
            try:
                if output is not None:
                    path = output / "Hisser" / PurePosixPath(relative)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    destination = path.open("xb")
                with bundle.open(info) as source:
                    while chunk := source.read(1024 * 1024):
                        digest.update(chunk)
                        size += len(chunk)
                        if size > record["size"]:
                            raise VerificationError("The archived stream exceeds its declared size")
                        if destination is not None:
                            destination.write(chunk)
            finally:
                if destination is not None:
                    destination.close()
            if size != record["size"] or digest.hexdigest() != record["sha256"]:
                raise VerificationError(f"The archived file checksum differs: {relative}")
            if relative.endswith((".json", ".md", ".txt")):
                if info.file_size > 2_000_000:
                    raise VerificationError("An unexpectedly large text record requires review")
                content = bundle.read(info).decode("utf-8-sig")
                if re.search(r"(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/]|/Users/|/home/|\\\\[^\s\\]+\\)", content):
                    raise VerificationError("A public record contains a local machine path")
        profile = _object(bundle.read("Hisser/data/transcription-profile.json"), "transcription profile")
        if profile != {"model_id": model.id, "cpu_threads": 6}:
            raise VerificationError("The release does not use the approved clean profile")
        metadata = _object(bundle.read("Hisser/" + model_relative + ".metadata.json"), "model metadata")
        if metadata.get("size") != model.size or metadata.get("sha256") != model.sha256:
            raise VerificationError("The model verification metadata differs from the catalog")
        marker = _object(bundle.read("Hisser/portable.json"), "portable marker")
        if marker.get("application_id") != packaging.APPLICATION_ID or marker.get("data_relative_path") != "data" or marker.get("portable") is not True:
            raise VerificationError("The release is not marked as a relative portable app")
        build = _object(bundle.read("Hisser/build-manifest.json"), "build manifest")
        if (build.get("version") != manifest["version"] or marker.get("version") != manifest["version"]
                or build.get("backend") != manifest["backend"] or build.get("model_id") != model.id
                or build.get("exe_sha256") != records_by_name["Hisser.exe"]["sha256"]):
            raise VerificationError("The release build/profile records do not match the verified files")
        if output is not None:
            (output / "Hisser/release-manifest.json").write_bytes(bundle.read(manifest_info))
    return {"verified": True, "archive_sha256": actual_sha256, "archive_bytes": archive.stat().st_size,
            "extracted_bytes": total, "file_count": len(infos), "version": manifest["version"],
            "model_id": model.id, "backend": manifest.get("backend"), "extracted": output is not None}


def clean_windows_environment() -> dict[str, str]:
    env = os.environ.copy()
    windows = Path(env.get("SystemRoot", r"C:\Windows"))
    env["PATH"] = str(windows / "System32") + os.pathsep + str(windows)
    for name in list(env):
        if name.upper().startswith(("PYTHON", "HISSER_", "CUDA_PATH")) or name.upper() in ("VIRTUAL_ENV", "CONDA_PREFIX", "TCL_LIBRARY", "TK_LIBRARY"):
            env.pop(name, None)
    return env


@contextmanager
def isolated_environment(env: dict[str, str]):
    previous = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(env)
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


def synthesize_fixture(destination: Path, env: dict[str, str]) -> None:
    windows = Path(env.get("SystemRoot", r"C:\Windows"))
    powershell = windows / "System32/WindowsPowerShell/v1.0/powershell.exe"
    quoted = str(destination).replace("'", "''")
    code = ("Add-Type -AssemblyName System.Speech; $speech = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$speech.SetOutputToWaveFile('" + quoted + "'); "
            "$speech.Speak('Hello. This is a short offline transcription test. Please keep this recording unchanged.'); $speech.Dispose()")
    subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", code], env=env,
                   check=True, capture_output=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)


def exercise_extracted(output: Path, *, audio: Path | None = None,
                       processing: list[str] | tuple[str, ...] = ("cpu", "auto"),
                       require_auto_backend: str | None = None) -> dict:
    """Exercise only a previously verified/extracted candidate; jobs stay serial."""
    if os.name != "nt":
        raise VerificationError("Executable validation requires Windows")
    from hisser.engine import Transcriber
    from hisser.exports import export_transcript
    app = output / "Hisser"
    if not (app / "release-manifest.json").is_file():
        raise VerificationError("Exercise a freshly verified/extracted release")
    env = clean_windows_environment()
    self_test_path = output / "frozen-self-test.json"
    if self_test_path.exists():
        raise VerificationError("The extraction was already exercised; use a fresh directory")
    subprocess.run([str(app / "Hisser.exe"), "--self-test", str(self_test_path)], cwd=app,
                   env=env, check=True, capture_output=True, timeout=120,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    self_test = _object(self_test_path.read_bytes(), "frozen startup report")
    for key in ("tk", "portable", "runtime_files", "model", "exports"):
        if not self_test.get(key):
            raise VerificationError(f"The extracted executable failed its {key} check")
    if Path(self_test.get("data_root", "")).resolve() != (app / "data").resolve():
        raise VerificationError("The extracted app writes data outside its own folder")
    profile = load_profile(app / "data")
    if self_test.get("model_id") != profile.model.id or self_test.get("cpu_threads") != 6:
        raise VerificationError("The extracted executable selected a different model/profile")
    if audio is None:
        audio = output / "Synthetic English - José & Niño.wav"
        synthesize_fixture(audio, env)
    else:
        audio = Path(audio).resolve()
    initial_hash = file_hash(audio)
    jobs = app / "data/temp"
    results = []
    with isolated_environment(env):
        for mode in processing:
            events = []
            engine = Transcriber(app / "_internal/runtime", app / "data/models" / profile.model.filename,
                                 jobs, processing=mode, threads=profile.cpu_threads, model_spec=profile.model)
            started = time.perf_counter()
            transcript = engine.run(audio, "en", events.append)
            elapsed = time.perf_counter() - started
            if not transcript.get("text", "").strip() or transcript.get("schema_version") != 1:
                raise VerificationError("Recognition did not produce a timed transcript")
            if profile.model.id not in transcript.get("engine", ""):
                raise VerificationError("The transcript identifies the wrong model")
            if mode == "cpu" and engine.actual_backend != "cpu":
                raise VerificationError("CPU mode did not use CPU")
            if mode == "auto" and require_auto_backend and engine.actual_backend != require_auto_backend:
                raise VerificationError("Automatic processing used an unexpected backend")
            destinations = {fmt: output / "Exports - José & Niño" / mode / ("Transcrição." + fmt)
                            for fmt in ("pdf", "srt", "txt", "vtt", "json")}
            next(iter(destinations.values())).parent.mkdir(parents=True)
            exported = export_transcript(transcript, destinations)
            if len(exported) != 5 or not all(path.is_file() and path.stat().st_size > 0 for path in exported):
                raise VerificationError("One or more transcript exports failed")
            if jobs.exists() and list(jobs.iterdir()):
                raise VerificationError("Temporary transcription files remain after completion")
            if file_hash(audio) != initial_hash:
                raise VerificationError("The source recording changed")
            results.append({"processing": mode, "actual_backend": engine.actual_backend,
                            "seconds": round(elapsed, 3), "timed_segments": len(transcript["segments"]),
                            "five_exports": True, "source_unchanged": True, "temporary_files_clean": True,
                            "cpu_retry_explained": any(event.get("fallback") for event in events)})
    return {"frozen_startup": True, "clean_windows_path": True, "portable_data_root": True,
            "unicode_extraction_path": any(ord(char) > 127 for char in str(output)),
            "model_id": profile.model.id, "synthetic_fixture": audio.name.startswith("Synthetic English"),
            "runs": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", "--zip", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output-directory", type=Path)
    parser.add_argument("--exercise", action="store_true")
    parser.add_argument("--test-audio", type=Path)
    parser.add_argument("--processing", choices=("cpu", "auto"), nargs="+", default=["cpu", "auto"])
    parser.add_argument("--require-auto-backend", choices=("cpu", "cuda"))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        if args.exercise and args.output_directory is None:
            raise VerificationError("Executable validation requires --output-directory")
        result = verify_archive(args.archive, args.sha256, args.output_directory)
        if args.exercise:
            result["exercise"] = exercise_extracted(args.output_directory.absolute(), audio=args.test_audio,
                processing=args.processing, require_auto_backend=args.require_auto_backend)
        if args.report:
            packaging.assert_plain_path(args.report)
            args.report.parent.mkdir(parents=True, exist_ok=True)
            with args.report.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, indent=2)
                stream.write("\n")
        print(json.dumps(result, indent=2))
    except (VerificationError, packaging.ReleaseError, OSError, ValueError, zipfile.BadZipFile,
            KeyError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Release validation stopped: {exc}\n")


if __name__ == "__main__":
    main()
