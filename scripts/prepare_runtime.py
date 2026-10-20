"""Prepare Hisser's pinned CPU runtime and one verified local model.

Uses only Python's standard library. Network access and the per-user model
directory must be authorized by the caller. Reruns resume incomplete downloads;
already verified files are reused. No global Python packages are changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
import urllib.error
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
DOWNLOADS = ROOT / "downloads"
QA = ROOT / "qa"
MODEL_NAME = "ggml-large-v3-q5_0.bin"
DEFAULT_MODEL_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Hisser" / "models"
MODEL_REVISION = "5359861c739e955e79d9a303bcbc70fb988958b1"
MODEL_SHA = "d75795ecff3f83b5faa89d1900604ad8c780abd5739fae406de19f23ecd98ad1"
MODEL_SIZE = 1_081_140_203
WHISPER_SHA = "6ba69e3482d7826214f90a6a9c84ca07782aec1e1d0c6a7c30c994fd5d816ccb"
WHISPER_URL = "https://github.com/ggml-org/whisper.cpp/releases/download/b5454/whisper-bin-x64.zip"
USER_AGENT = "Hisser-setup/1.0 (personal-local-Windows-app)"


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def request(url, headers=None):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})}), timeout=90)


def get_json(url):
    with request(url) as response:
        return json.load(response)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def checked_download(url, destination, expected_sha, expected_size):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.stat().st_size == expected_size and sha256(destination) == expected_sha:
            print(f"Verified existing {destination.name}: {expected_size:,} bytes", flush=True)
            return
        raise RuntimeError(f"Existing {destination} does not match upstream metadata; preserved for review.")
    partial = destination.with_name(destination.name + ".part")
    for attempt in range(1, 6):
        existing = partial.stat().st_size if partial.exists() else 0
        if existing == expected_size:
            break
        if existing > expected_size:
            raise RuntimeError(f"Oversize partial download preserved: {partial}")
        try:
            headers = {"Range": f"bytes={existing}-"} if existing else {}
            with request(url, headers) as response:
                resume = existing and response.status == 206
                if existing and not resume:
                    print(f"Server restarted {destination.name}; replacing only this setup partial", flush=True)
                    existing = 0
                total = existing
                last_update = time.monotonic()
                with partial.open("ab" if resume else "wb") as stream:
                    while block := response.read(4 * 1024 * 1024):
                        stream.write(block)
                        total += len(block)
                        if time.monotonic() - last_update >= 10:
                            print(f"Downloading {destination.name}: {total:,}/{expected_size:,} bytes ({total / expected_size:.0%})", flush=True)
                            last_update = time.monotonic()
            if partial.stat().st_size == expected_size:
                break
            raise RuntimeError(f"Incomplete transfer: {partial.stat().st_size:,}/{expected_size:,}")
        except (OSError, RuntimeError, urllib.error.URLError) as error:
            if attempt == 5:
                raise
            print(f"Download interrupted ({error}); resuming attempt {attempt + 1}", flush=True)
            time.sleep(min(attempt * 2, 8))
    actual = sha256(partial)
    if partial.stat().st_size != expected_size or actual != expected_sha:
        raise RuntimeError(f"SHA-256 mismatch for {partial}: {actual}; partial preserved, never executed.")
    partial.replace(destination)
    print(f"Verified {destination.name}: SHA-256 {actual}", flush=True)


def capture(args, timeout=60):
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), shell=False)
    return {"exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def scan(path):
    base = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "Microsoft" / "Windows Defender" / "Platform"
    candidates = sorted(base.glob("*/MpCmdRun.exe"), reverse=True)
    candidates.append(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Windows Defender" / "MpCmdRun.exe")
    executable = next((p for p in candidates if p.exists()), None)
    if executable is None:
        return {"status": "unavailable", "reason": "Windows Defender MpCmdRun.exe was not found."}
    print(f"Windows Security targeted scan: {path}", flush=True)
    try:
        result = capture([str(executable), "-Scan", "-ScanType", "3", "-File", str(path)], timeout=900)
    except Exception as error:
        return {"status": "failed", "executable": str(executable), "error": str(error)}
    return {"status": "completed" if result["exit_code"] == 0 else "failed_or_attention_required", "executable": str(executable), **result}


def bundle_msvc():
    """Copy only the CPU CLI's dependencies from this PC's installed redist."""
    sources = []
    for name in ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll", "vcomp140.dll"):
        source = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / name
        if not source.is_file():
            raise RuntimeError(f"Required Microsoft runtime is absent: {source}")
        literal = str(source).replace("'", "''")
        signature_command = ("[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); "
                             f"$s=Get-AuthenticodeSignature -LiteralPath '{literal}'; "
                             f"$f=Get-Item -LiteralPath '{literal}'; "
                             "[pscustomobject]@{status=[string]$s.Status;signer=$s.SignerCertificate.Subject;version=$f.VersionInfo.FileVersion}|ConvertTo-Json -Compress")
        signature_result = capture([shutil.which("pwsh") or "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", signature_command])
        signature = json.loads(signature_result["stdout"].lstrip("\ufeff"))
        if signature_result["exit_code"] != 0 or signature["status"] != "Valid" or "Microsoft" not in signature["signer"]:
            raise RuntimeError(f"Microsoft runtime signature did not validate: {source}")
        shutil.copy2(source, RUNTIME / name)
        sources.append({"name": name, "existing_source": str(source), "sha256": sha256(source), "size": source.stat().st_size, **signature})
    (RUNTIME / "licenses" / "Microsoft-runtime-NOTICE.txt").write_text(
        "Microsoft Visual C++ / OpenMP runtime dependencies copied from the user's existing Windows installation for this personal app.\n"
        "Copyright Microsoft Corporation. Subject to Microsoft's applicable runtime license.\n"
        "Official redistributable information: https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist\n"
        "No global runtime installation or system file was changed.\n", encoding="utf-8")
    return sources


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-directory", type=Path, default=DEFAULT_MODEL_DIR,
                        help="Store the approved model here (default: %%LOCALAPPDATA%%/Hisser/models).")
    parser.add_argument("--skip-model", action="store_true")
    parser.add_argument("--skip-scan", action="store_true")
    args = parser.parse_args()
    model_dir = args.model_directory.expanduser().resolve()
    for directory in (RUNTIME, DOWNLOADS, QA, RUNTIME / "licenses"):
        directory.mkdir(parents=True, exist_ok=True)
    report = {"started_utc": now(), "cpu_only": True, "scans": {}}
    tree_url = f"https://huggingface.co/api/models/ggerganov/whisper.cpp/tree/{MODEL_REVISION}?recursive=false&expand=false"
    model_url = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/{MODEL_REVISION}/{MODEL_NAME}"
    model = model_dir / MODEL_NAME
    provenance = {"prepared_utc": now(), "whisper": {}, "ffmpeg": {}, "model": {
        "name": MODEL_NAME, "path": str(model), "repository": "ggerganov/whisper.cpp",
        "revision": MODEL_REVISION, "download_url": model_url, "metadata_url": tree_url,
        "size": MODEL_SIZE, "sha256": MODEL_SHA, "license": "MIT",
        "source_format": "whisper.cpp multilingual GGML large-v3 quantized Q5_0",
    }}

    release_url = "https://api.github.com/repos/ggml-org/whisper.cpp/releases/tags/b5454"
    release = get_json(release_url)
    asset = next(a for a in release["assets"] if a["name"] == "whisper-bin-x64.zip")
    if asset["browser_download_url"] != WHISPER_URL or asset.get("digest") != "sha256:" + WHISPER_SHA:
        raise RuntimeError("Official GitHub asset metadata did not match the pinned CPU release.")
    archive = DOWNLOADS / "whisper-bin-x64-b5454.zip"
    checked_download(WHISPER_URL, archive, WHISPER_SHA, asset["size"])
    extracted = []
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            name = Path(member.filename).name
            if name == "whisper-cli.exe" or (name.lower().endswith(".dll") and (name.startswith("ggml") or name == "whisper.dll")):
                destination = RUNTIME / name
                with bundle.open(member) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
                extracted.append(name)
    if "whisper-cli.exe" not in extracted:
        raise RuntimeError("Verified archive had no whisper-cli.exe.")
    license_url = "https://raw.githubusercontent.com/ggml-org/whisper.cpp/b5454/LICENSE"
    with request(license_url) as response:
        (RUNTIME / "licenses" / "whisper.cpp-LICENSE.txt").write_bytes(response.read())
    provenance["whisper"] = {"stable_release": "v1.9.5", "stable_release_url": "https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.5",
                             "binary_tag": "b5454", "source_commit": release.get("target_commitish"), "release_metadata_url": release_url,
                             "download_url": WHISPER_URL, "archive_size": asset["size"], "archive_sha256": WHISPER_SHA, "files": extracted,
                             "license_url": license_url}
    provenance["microsoft_runtime"] = bundle_msvc()
    language_url = "https://raw.githubusercontent.com/ggml-org/whisper.cpp/b5454/src/whisper.cpp"
    with request(language_url) as response:
        language_source = response.read().decode("utf-8")
    languages = [{"code": code, "name": name.title()} for code, name in re.findall(r'\{ "([a-z]+)",\s*\{\s*\d+,\s*"([a-z ]+)"', language_source)]
    write_json(RUNTIME / "languages.json", {"source_url": language_url, "languages": languages})
    archive.unlink()
    print("Removed verified setup ZIP; retained runtime files only.", flush=True)

    ffmpeg = Path(shutil.which("ffmpeg") or "")
    ffprobe = Path(shutil.which("ffprobe") or "")
    if not ffmpeg.is_file() or not ffprobe.is_file():
        raise RuntimeError("The existing FFmpeg and ffprobe must be available on PATH.")
    for source, name in ((ffmpeg, "ffmpeg.exe"), (ffprobe, "ffprobe.exe")):
        destination = RUNTIME / name
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
    version = capture([str(RUNTIME / "ffmpeg.exe"), "-version"])
    probe_version = capture([str(RUNTIME / "ffprobe.exe"), "-version"])
    build = capture([str(RUNTIME / "ffmpeg.exe"), "-buildconf"])
    license_output = capture([str(RUNTIME / "ffmpeg.exe"), "-L"])
    if any(result["exit_code"] != 0 for result in (version, probe_version, build, license_output)):
        raise RuntimeError("The selected FFmpeg/ffprobe did not report a working version, license and build configuration.")
    version_match = re.search(r"^ffmpeg version (\d+\.\d+(?:\.\d+)?)(?:[-\s]|$)", version["stdout"], re.MULTILINE)
    probe_match = re.search(r"^ffprobe version (\d+\.\d+(?:\.\d+)?)(?:[-\s]|$)", probe_version["stdout"], re.MULTILINE)
    selected_version = version_match.group(1) if version_match else None
    if selected_version and probe_match and selected_version != probe_match.group(1):
        raise RuntimeError("FFmpeg and ffprobe on PATH have different release versions. Select a matching pair.")
    (RUNTIME / "licenses" / "FFmpeg-license-output.txt").write_text(license_output["stdout"] + license_output["stderr"], encoding="utf-8")
    original_license = ffmpeg.parent.parent / "LICENSE"
    if not original_license.exists():
        original_license = ffmpeg.parent.parent / "LICENSE.txt"
    if original_license.exists():
        shutil.copy2(original_license, RUNTIME / "licenses" / "FFmpeg-LICENSE.txt")
    elif selected_version:
        configuration = build["stdout"] + build["stderr"]
        license_name = "COPYING.GPLv3" if "--enable-gpl" in configuration and "--enable-version3" in configuration else ("COPYING.GPLv2" if "--enable-gpl" in configuration else ("COPYING.LGPLv3" if "--enable-version3" in configuration else "COPYING.LGPLv2.1"))
        with request(f"https://raw.githubusercontent.com/FFmpeg/FFmpeg/n{selected_version}/{license_name}") as response:
            (RUNTIME / "licenses" / ("FFmpeg-" + license_name + ".txt")).write_bytes(response.read())
    (RUNTIME / "licenses" / "FFmpeg-buildconf.txt").write_text(build["stdout"] + build["stderr"], encoding="utf-8")
    provenance["ffmpeg"] = {"existing_source": str(ffmpeg), "existing_ffprobe_source": str(ffprobe),
                            "version_output": version["stdout"], "ffprobe_version_output": probe_version["stdout"],
                            "release_version": selected_version,
                            "distributor": "Existing FFmpeg executables supplied on PATH; see version and build configuration",
                            "upstream_source_url": (f"https://github.com/FFmpeg/FFmpeg/tree/n{selected_version}" if selected_version else "https://github.com/FFmpeg/FFmpeg"),
                            "license": "See bundled original license, license output and build configuration"}

    if not args.skip_model:
        entries = get_json(tree_url)
        metadata = next(entry for entry in entries if entry["path"] == MODEL_NAME)
        model_sha = metadata["lfs"]["oid"]
        model_size = metadata["lfs"]["size"]
        if model_size != MODEL_SIZE or metadata["size"] != MODEL_SIZE or model_sha != MODEL_SHA:
            raise RuntimeError("Upstream model LFS metadata did not match the approved pinned revision, size and SHA-256. No replacement model was downloaded.")
        write_json(QA / "model-upstream-metadata.json", provenance["model"])
        checked_download(model_url, model, model_sha, model_size)
        write_json(model.with_name(model.name + ".metadata.json"), provenance["model"])
        report["model"] = {"verified": True, "size": model_size, "sha256": model_sha}
    else:
        report["model"] = {"verified": False, "reason": "Skipped by caller"}
    provenance["runtime_files"] = [{"name": p.name, "size": p.stat().st_size, "sha256": sha256(p)} for p in sorted(RUNTIME.iterdir()) if p.is_file() and p.name != "provenance.json"]
    write_json(RUNTIME / "provenance.json", provenance)
    if not args.skip_scan:
        report["scans"]["runtime"] = scan(RUNTIME)
        if not args.skip_model:
            report["scans"]["model"] = scan(model)
            if report["scans"]["model"]["status"] != "completed":
                report["scans"]["model_folder_retry"] = scan(model_dir)
    else:
        report["scans"] = {"status": "not_run", "reason": "Skipped by caller"}
    help_result = capture([str(RUNTIME / "whisper-cli.exe"), "--help"])
    (QA / "whisper-cli-help.txt").write_text(help_result["stdout"] + help_result["stderr"], encoding="utf-8")
    report["whisper_help_exit_code"] = help_result["exit_code"]
    report["runtime_bytes"] = sum(p.stat().st_size for p in RUNTIME.rglob("*") if p.is_file())
    report["model_bytes"] = 0 if args.skip_model else model.stat().st_size
    report["runtime_plus_model_bytes"] = report["runtime_bytes"] + report["model_bytes"]
    report["finished_utc"] = now()
    write_json(QA / "runtime-verification.json", report)
    print(json.dumps({k: v for k, v in report.items() if k not in ("scans",)}, indent=2), flush=True)
    print("Targeted scans: " + json.dumps({k: v.get("status") for k, v in report["scans"].items() if isinstance(v, dict)}), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Runtime preparation failed: {error}", file=sys.stderr, flush=True)
        raise
