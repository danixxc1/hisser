"""Reproducible actual local-engine QA using synthetic Windows speech.

Use --short, --failures, or --long. Long QA processes the complete 30+ minute
recording; it never substitutes generated timestamps for recognition evidence.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import wave

import psutil

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hisser.engine import Cancelled, Transcriber, TranscriptionError
from hisser.models import model_for_filename

QA = ROOT / "qa" / "engine-integration"
INPUTS = QA / "José Mañalac - synthetic fixtures"
MODEL = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Hisser/models/ggml-large-v3-q5_0.bin"
RUNTIME = ROOT / "runtime"
PROCESSING = "cpu"
THREADS = 2
PWSH = Path(shutil.which("powershell.exe") or shutil.which("pwsh") or
            Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe")
VOICE = "Microsoft Zira Desktop"
SHORT_TEXT = ("Hello. This is a Hisser transcription test. Maria brought three blue notebooks "
              "to the library. The secret phrase is silver mango lantern. This recording ends here.")
LATE_TEXT = ("After thirty minutes, the final checkpoint is purple coconut bicycle. "
             "Maria has reached the end of the recording.")


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def child_run(args):
    return subprocess.run(args, check=True, stdin=subprocess.DEVNULL, capture_output=True,
                          creationflags=subprocess.CREATE_NO_WINDOW, text=True, encoding="utf-8", errors="replace")


def synthesize(path: Path, text: str):
    if path.is_file():
        return
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    code = ("$ErrorActionPreference = 'Stop'; Add-Type -AssemblyName System.Speech; "
            "$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$voice.SelectVoice(" + quote(VOICE) + "); $voice.Rate = -1; "
            "$voice.SetOutputToWaveFile(" + quote(path) + "); "
            "$voice.Speak(" + quote(text) + "); $voice.Dispose()")
    child_run([str(PWSH), "-NoProfile", "-NonInteractive", "-Command", code])


def prepare_short():
    INPUTS.mkdir(parents=True, exist_ok=True)
    path = INPUTS / "Prueba ni José - clear English.wav"
    synthesize(path, SHORT_TEXT)
    with wave.open(str(path), "rb") as wav:
        duration_ms = round(wav.getnframes() * 1000 / wav.getframerate())
    manifest_path = QA / "fixture-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    manifest.update({
        "synthetic": True, "speech_engine": "Windows " + VOICE + " / System.Speech",
        "voice_rate": -1, "short_path": str(path), "short_duration_ms": duration_ms,
        "short_expected_text": SHORT_TEXT,
        "late_expected_text": LATE_TEXT,
        "accuracy_scope": "Synthetic clear English only. Film and Tagalog accuracy are untested.",
    })
    write_json(manifest_path, manifest)
    return path


def measure_job(label: str, source: Path, cancel_at_inference: bool = False, language: str = "en"):
    descriptor = model_for_filename(MODEL.name)
    engine = Transcriber(RUNTIME, MODEL, QA / "jobs", processing=PROCESSING,
                         threads=THREADS, model_spec=descriptor)
    stop = threading.Event()
    samples = {"peak_child_rss_bytes": 0, "peak_whisper_rss_bytes": 0, "peak_child_total_rss_bytes": 0,
               "peak_parent_rss_bytes": 0, "sample_interval_seconds": 0.2}
    started = time.monotonic()
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    first_inference = None
    cancelled = False
    last_progress = None
    log_path = QA / (label + "-events.jsonl")

    def sample():
        nonlocal first_inference, cancelled
        parent = psutil.Process(os.getpid())
        last_telemetry = 0
        while not stop.wait(0.2):
            try:
                children = parent.children(recursive=True)
                total = 0
                samples["peak_parent_rss_bytes"] = max(samples["peak_parent_rss_bytes"], parent.memory_info().rss)
                for child in children:
                    try:
                        name = child.name().lower()
                        rss = child.memory_info().rss
                        total += rss
                        samples["peak_child_rss_bytes"] = max(samples["peak_child_rss_bytes"], rss)
                        if name == "whisper-cli.exe":
                            samples["whisper_priority_class"] = int(child.nice())
                            samples["peak_whisper_rss_bytes"] = max(samples["peak_whisper_rss_bytes"], rss)
                            if first_inference is None:
                                first_inference = time.monotonic()
                            if cancel_at_inference and not cancelled and time.monotonic() - first_inference > 0.5:
                                cancelled = True
                                engine.cancel()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                samples["peak_child_total_rss_bytes"] = max(samples["peak_child_total_rss_bytes"], total)
                elapsed = time.monotonic() - started
                if elapsed - last_telemetry >= 5:
                    write_json(QA / (label + "-telemetry.json"), {"elapsed_seconds": round(elapsed, 2), **samples})
                    last_telemetry = elapsed
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    result = None
    error = None
    with log_path.open("w", encoding="utf-8") as log:
        def emit(event):
            nonlocal last_progress
            record = {"elapsed_seconds": round(time.monotonic() - started, 3), **event}
            log.write(json.dumps(record, ensure_ascii=False) + "\n")
            log.flush()
            last_progress = record
            write_json(QA / (label + "-progress.json"), record)
            print(json.dumps({"job": label, **record}, ensure_ascii=False), flush=True)

        try:
            result = engine.run(source, language, emit)
            write_json(QA / (label + "-transcript.json"), result)
        except Exception as exc:
            error = {"type": type(exc).__name__, "message": str(exc)}
        finally:
            stop.set()
            sampler.join(timeout=2)
    report = {
        "label": label, "synthetic": True, "source": str(source),
        "engine": result.get("engine") if result else engine._engine_label(engine.actual_backend),
        "model_id": descriptor.id if descriptor else None, "model_file": MODEL.name,
        "model_size_bytes": MODEL.stat().st_size, "model_expected_sha256": descriptor.sha256 if descriptor else None,
        "threads": THREADS, "processors": 1, "processing_requested": PROCESSING,
        "gpu": engine.actual_backend == "cuda", "cancel_delay_after_child_seen_seconds": 0.5 if cancel_at_inference else None,
        "language_requested": language, "wall_seconds": round(time.monotonic() - started, 3),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(), "memory": samples,
        "error": error, "temp_clean": not list((QA / "jobs").glob("*")), "last_event": last_progress,
        "duration_ms": result["duration_ms"] if result else None,
        "recognized_text": result["text"] if result else None,
        "language_detected": result["language"] if result else None,
        "source_sha256_before": source_sha256,
        "source_sha256_after": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    if cancel_at_inference:
        report["accepted"] = bool(error and error["type"] == "Cancelled" and report["temp_clean"] and cancelled)
    elif result:
        phrase = "purple coconut bicycle" if label == "long" else "silver mango lantern"
        normalize = lambda value: " ".join(value.lower().replace(",", " ").replace(".", " ").split())
        report["known_phrase"] = phrase
        report["known_phrase_recognized"] = phrase in normalize(result["text"])
        report["accepted"] = report["known_phrase_recognized"] and report["temp_clean"]
        if label == "long":
            late_segments = [segment for segment in result["segments"] if segment["start_ms"] >= 1_800_000]
            report["late_segments"] = late_segments
            late_text = " ".join(segment["text"] for segment in late_segments)
            report["late_phrase_recognized_after_minute_30"] = phrase in normalize(late_text)
            report["accepted"] = report["accepted"] and report["late_phrase_recognized_after_minute_30"]
    else:
        report["accepted"] = False
    report["source_unchanged"] = report["source_sha256_before"] == report["source_sha256_after"]
    report["accepted"] = report["accepted"] and report["source_unchanged"]
    write_json(QA / (label + "-report.json"), report)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return report


def prepare_long(short: Path):
    late_raw = INPUTS / "Late checkpoint speech.wav"
    synthesize(late_raw, LATE_TEXT)
    long_path = INPUTS / "Película sintética - leading silence then speech after minute 30.flac"
    if long_path.is_file():
        probe = child_run([str(RUNTIME / "ffprobe.exe"), "-v", "error", "-show_entries", "format=duration",
                           "-of", "json", str(long_path)])
        duration_ms = round(float(json.loads(probe.stdout)["format"]["duration"]) * 1000)
        manifest_path = QA / "fixture-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update({"long_path": str(long_path), "late_speech_start_ms": 1_830_000,
                         "long_duration_ms": duration_ms, "existing_long_fixture_reused": True,
                         "long_fixture_structure": "Existing controlled fixture: exact leading PCM zero samples until 30:30, then known late speech.",
                         "optimization_under_test": "Full decode and complete PCM scan; only exact-zero outer silence is trimmed. Real late speech recognition and original timestamps must pass."})
        write_json(manifest_path, manifest)
        return long_path
    converted = []
    for index, source in enumerate((late_raw,)):
        output = INPUTS / f"setup-{index}-16k.wav"
        child_run([str(RUNTIME / "ffmpeg.exe"), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                   "-i", str(source), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(output)])
        converted.append(output)
    long_wav = INPUTS / "setup-long.wav"
    with wave.open(str(converted[0]), "rb") as late:
        late_frames = late.readframes(late.getnframes())
    late_start_ms = 1_830_000
    silence_frames = late_start_ms * 16
    with wave.open(str(long_wav), "wb") as out:
        out.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        block = bytes(16000 * 2)
        while silence_frames > 0:
            frames = min(silence_frames, 16000)
            out.writeframes(block[:frames * 2])
            silence_frames -= frames
        out.writeframes(late_frames)
    child_run([str(RUNTIME / "ffmpeg.exe"), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
               "-i", str(long_wav), "-c:a", "flac", str(long_path)])
    for generated in [long_wav, *converted]:
        generated.unlink()
    manifest_path = QA / "fixture-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update({"long_path": str(long_path), "late_speech_start_ms":late_start_ms,
                     "long_duration_ms": late_start_ms + len(late_frames) // 32,
                     "long_fixture_structure": "Exact leading PCM zero samples until 30:30, then known late speech.",
                     "optimization_under_test": "Full decode and complete PCM scan; only exact-zero leading/trailing spans of at least 30s are trimmed, keeping 500ms context. One real inference pass; timings offset to original full duration."})
    write_json(manifest_path, manifest)
    return long_path


def failures(short):
    results = []
    missing = INPUTS / "missing-media.mp4"
    corrupt = INPUTS / "Corrupt media.mp4"
    corrupt.write_bytes(b"This is deliberately not playable media.")
    no_audio = INPUTS / "Silent picture - no audio track.mp4"
    if not no_audio.is_file():
        child_run([str(RUNTIME / "ffmpeg.exe"), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                   "-f", "lavfi", "-i", "color=c=black:s=64x64:r=1:d=1", "-an", "-c:v", "mpeg4", str(no_audio)])
    bad_model = INPUTS / "corrupt-model.bin"
    bad_model.write_bytes(b"BAD!" + bytes(124))
    for label, source, model, expected in (
        ("missing_media", missing, MODEL, "selected file is missing"),
        ("corrupt_media", corrupt, MODEL, "Media inspection failed"),
        ("no_audio", no_audio, MODEL, "no audio track"),
        ("missing_model", short, INPUTS / "missing-model.bin", "model is missing"),
        ("corrupt_model", short, bad_model, "model is corrupt"),
    ):
        error = None
        try:
            Transcriber(RUNTIME, model, QA / "jobs", processing=PROCESSING, threads=THREADS).run(source, "en", lambda event: None)
        except TranscriptionError as exc:
            error = str(exc)
        accepted = error is not None and expected in error and not list((QA / "jobs").glob("*"))
        results.append({"case": label, "accepted": accepted, "error": error})
    results.append(measure_job("cancel-inference", short, cancel_at_inference=True))
    results.append(measure_job("retry-after-cancel", short))
    write_json(QA / "failure-retry-report.json", {"synthetic": True, "cases": results,
                                                "accepted": all(case["accepted"] for case in results)})
    bad_model.unlink()
    return all(case["accepted"] for case in results)


def main():
    global QA, INPUTS, MODEL, RUNTIME, PWSH, VOICE, PROCESSING, THREADS
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-directory", type=Path, default=RUNTIME,
                        help="Folder containing whisper-cli.exe, ffmpeg.exe and ffprobe.exe.")
    parser.add_argument("--model", type=Path, default=MODEL,
                        help="Path to a verified local GGML model; the catalog descriptor selects actual model metadata.")
    parser.add_argument("--output-directory", type=Path, default=QA,
                        help="Local-only synthetic fixtures and diagnostic reports.")
    parser.add_argument("--fixtures-directory", type=Path,
                        help="Reuse a dedicated existing synthetic fixture folder; reports still use --output-directory.")
    parser.add_argument("--processing", choices=("cpu", "auto"), default="cpu",
                        help="CPU (default), or Automatic GPU processing with the app's normal CPU fallback.")
    parser.add_argument("--threads", type=int, choices=range(1, 33), default=2,
                        help="Inference CPU threads, 1 through 32 (default: 2).")
    parser.add_argument("--powershell", type=Path, default=PWSH,
                        help="Windows PowerShell or pwsh executable with System.Speech available.")
    parser.add_argument("--voice", default=VOICE,
                        help="Installed English System.Speech voice used for synthetic fixtures.")
    parser.add_argument("--short", action="store_true")
    parser.add_argument("--long", action="store_true")
    parser.add_argument("--failures", action="store_true")
    parser.add_argument("--auto", action="store_true", help="Also test automatic language detection.")
    args = parser.parse_args()
    if not any((args.short, args.long, args.failures, args.auto)):
        parser.error("Choose --short, --auto, --failures or --long. These are actual local model tests.")
    QA = args.output_directory.expanduser().resolve()
    INPUTS = args.fixtures_directory.expanduser().resolve() if args.fixtures_directory else QA / "José Mañalac - synthetic fixtures"
    MODEL = args.model.expanduser().resolve()
    RUNTIME = args.runtime_directory.expanduser().resolve()
    PWSH = args.powershell.expanduser().resolve()
    VOICE = args.voice
    PROCESSING = args.processing
    THREADS = args.threads
    if os.name != "nt":
        parser.error("Actual speech acceptance requires Windows and System.Speech.")
    if not PWSH.is_file() or not MODEL.is_file():
        parser.error("The selected PowerShell executable or approved local model is missing. Use --powershell and --model to select them.")
    for name in ("whisper-cli.exe", "ffmpeg.exe", "ffprobe.exe"):
        if not (RUNTIME / name).is_file():
            parser.error(f"Missing runtime file: {RUNTIME / name}")
    if any((process.info.get("name") or "").lower() == "whisper-cli.exe"
           for process in psutil.process_iter(["name"])):
        parser.error("A whisper-cli.exe process is already running. Wait for it to finish before starting acceptance.")
    QA.mkdir(parents=True, exist_ok=True)
    short = prepare_short()
    accepted = True
    if args.short:
        accepted = measure_job("short", short)["accepted"] and accepted
    if args.auto:
        report = measure_job("auto-language", short, language="auto")
        accepted = report["accepted"] and report["language_detected"] == "en" and accepted
    if args.failures:
        accepted = failures(short) and accepted
    if args.long:
        long_path = prepare_long(short)
        report = measure_job("long", long_path)
        accepted = report["accepted"] and accepted
        # Retain the compact lossless source and JSON evidence. Engine always
        # removes its own decoded audio; no 60 MB setup WAV is retained.
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
