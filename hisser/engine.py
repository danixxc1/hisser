"""Local, cancellable FFmpeg → whisper.cpp transcription worker.

Only this module's owned child process is terminated by ``cancel``.  The caller
runs ``run`` on a worker thread and forwards its event dictionaries to the UI.
The model is never opened until a job starts.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import queue
import re
import subprocess
import tempfile
import threading
import time
from typing import Callable
import wave


class TranscriptionError(RuntimeError):
    """An actionable media, runtime, or recognition failure."""


class Cancelled(TranscriptionError):
    """The current job was cancelled; no result should be displayed as complete."""


SUPPORTED_LANGUAGES = frozenset(
    "en zh de es ru ko fr ja pt tr pl ca nl ar sv it id hi fi vi he uk el ms cs "
    "ro da hu ta no th ur hr bg lt la mi ml cy sk te fa lv bn sr az sl kn et mk "
    "br eu is hy ne mn bs kk sq sw gl mr pa si km sn yo so af oc ka be tg sd gu "
    "am yi lo uz fo ht ps tk nn mt sa lb my bo tl mg as tt haw ln ha ba jw su yue".split()
)

_PERCENT = re.compile(r"progress\s*[=:]\s*(\d{1,3}(?:\.\d+)?)\s*%", re.IGNORECASE)
_MAX_LOG_CHARS = 1800
_ENGINE = "whisper.cpp b5454 / large-v3-q5_0"


def _seconds_to_ms(value: object) -> int:
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        return 0
    return round(seconds * 1000) if math.isfinite(seconds) and seconds > 0 else 0


def _bounded_detail(lines: deque[str]) -> str:
    # Remove control characters before a native error dialog sees external logs.
    detail = "\n".join(lines)
    detail = "".join(c for c in detail if c in "\n\t" or ord(c) >= 32)
    return detail[-_MAX_LOG_CHARS:].strip()


class Transcriber:
    def __init__(self, runtime_dir: Path, model_path: Path, temp_root: Path | None = None):
        self.runtime_dir = Path(runtime_dir).resolve()
        self.model_path = Path(model_path).resolve()
        self.temp_root = Path(temp_root).resolve() if temp_root is not None else None
        self._cancelled = threading.Event()
        self._run_lock = threading.Lock()
        self._process_lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._has_run = False

    def cancel(self) -> None:
        """Request cancellation without waiting for the worker to finish."""
        self._cancelled.set()
        with self._process_lock:
            process = self._process
            if process is not None and process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    pass  # The process may have exited between poll and terminate.

    def _check_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise Cancelled("Transcription cancelled. Temporary audio has been removed.")

    def _validate(self, source: Path, language: str) -> None:
        if not source.is_file():
            raise TranscriptionError("The selected file is missing. Select it again and retry.")
        if language != "auto" and language not in SUPPORTED_LANGUAGES:
            raise TranscriptionError("Choose Auto detect or a supported transcription language.")
        for name in ("ffmpeg.exe", "ffprobe.exe", "whisper-cli.exe"):
            if not (self.runtime_dir / name).is_file():
                raise TranscriptionError(f"Hisser is missing {name}. Restore the complete Hisser folder, including its _internal folder, and retry.")
        if not self.model_path.is_file():
            raise TranscriptionError("The local Whisper model is missing. Restore data/models/ggml-large-v3-q5_0.bin inside the Hisser folder and retry.")
        try:
            with self.model_path.open("rb") as model:
                magic = model.read(4)
            size = self.model_path.stat().st_size
        except OSError as exc:
            raise TranscriptionError("Hisser cannot read its local model. Check file permissions and retry.") from exc
        # GGML_FILE_MAGIC 0x67676d6c is stored little-endian by whisper.cpp.
        if magic != b"lmgg" or size < 64:
            raise TranscriptionError("The local model is corrupt or is not a whisper.cpp GGML model. Restore the verified model in Hisser's data/models folder.")
        metadata_path = self.model_path.with_suffix(self.model_path.suffix + ".metadata.json")
        if metadata_path.is_file():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                expected_size = metadata.get("size", metadata.get("size_bytes"))
                if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size <= 0:
                    raise ValueError("invalid size")
            except (OSError, ValueError, TypeError, AttributeError) as exc:
                raise TranscriptionError("The model verification record is damaged. Restore the verified model and its metadata file in data/models.") from exc
            if size != expected_size:
                raise TranscriptionError("The local model download is incomplete or damaged. Restore the verified model in data/models and retry.")

    def run(self, source: Path, language: str, emit: Callable[[dict], None]) -> dict:
        """Transcribe the entire file once and return the canonical timed transcript.

        Events have ``kind`` (status/progress), ``phase`` (checking/decoding/
        transcribing/finalizing), ``message``, and optionally ``percent``. No
        completion event is emitted: only a successful return is completion.
        """
        if not self._run_lock.acquire(blocking=False):
            raise TranscriptionError("A transcription is already running. Cancel it or wait for it to finish.")
        try:
            # A fresh UI worker may receive Cancel before its thread enters run.
            # Retain that request; clear the previous job only when reusing an
            # instance for an explicit retry.
            if self._has_run:
                self._cancelled.clear()
            self._has_run = True
            source = Path(source).resolve()
            language = str(language).strip().lower()
            emit({"kind": "status", "phase": "checking", "message": "Checking file and local model…"})
            self._check_cancelled()
            self._validate(source, language)
            duration_ms = self._probe(source)
            self._check_cancelled()
            if self.temp_root is not None:
                self.temp_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="hisser-", dir=self.temp_root) as temp_dir:
                work = Path(temp_dir)
                audio = work / "audio.wav"
                emit({"kind": "status", "phase": "decoding", "message": "Preparing audio…", "percent": 0})
                decode_progress = self._decode_progress(emit, duration_ms)
                self._run_process([
                    str(self.runtime_dir / "ffmpeg.exe"), "-nostdin", "-hide_banner", "-loglevel", "error",
                    "-y", "-protocol_whitelist", "file,pipe", "-i", str(source), "-map", "0:a:0", "-vn", "-sn", "-dn",
                    "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
                    "-progress", "pipe:1", "-nostats", str(audio),
                ], "Audio preparation", decode_progress)
                self._check_cancelled()
                try:
                    with wave.open(str(audio), "rb") as wav:
                        if wav.getnchannels() != 1 or wav.getframerate() != 16000 or wav.getsampwidth() != 2:
                            raise ValueError("wrong audio format")
                        duration_ms = round(wav.getnframes() * 1000 / wav.getframerate())
                except (OSError, EOFError, wave.Error, ValueError) as exc:
                    raise TranscriptionError("Audio preparation did not produce readable audio. Try another media file.") from exc
                if duration_ms <= 0:
                    raise TranscriptionError("This file has no audio samples to transcribe. Select a file with recorded audio.")
                inference_audio, offset_ms = self._trim_digital_silence(audio, emit)
                if inference_audio is None:
                    self._check_cancelled()
                    emit({"kind": "status", "phase": "finalizing", "message": "The file contains only digital silence."})
                    self._check_cancelled()
                    return self._canonical({"transcription": []}, source, language, duration_ms)
                emit({"kind": "status", "phase": "transcribing", "message": "Loading model and transcribing on CPU…", "percent": 0})
                output = work / "transcript"
                self._run_process([
                    str(self.runtime_dir / "whisper-cli.exe"), "-m", str(self.model_path),
                    "-f", str(inference_audio), "-l", language, "-t", "2", "-p", "1", "-ng",
                    "-pp", "-ojf", "-of", str(output),
                ], "Transcription", self._inference_progress(emit))
                self._check_cancelled()
                emit({"kind": "status", "phase": "finalizing", "message": "Preparing transcript…"})
                try:
                    raw = json.loads(output.with_suffix(".json").read_text(encoding="utf-8-sig"))
                except (OSError, ValueError) as exc:
                    raise TranscriptionError("Whisper did not produce a readable transcript. Retry the file; if it persists, restore the model.") from exc
                result = self._canonical(raw, source, language, duration_ms, offset_ms=offset_ms)
                self._check_cancelled()
            return result
        except OSError as exc:
            if exc.errno == 28 or getattr(exc, "winerror", None) == 112:
                raise TranscriptionError("There is not enough temporary disk space. Free some space and retry. Prepared audio needs about 115 MB per hour.") from exc
            raise TranscriptionError(f"Hisser could not access a required file: {str(exc)[:350]}") from exc
        finally:
            self._run_lock.release()

    def _probe(self, source: Path) -> int:
        output = self._run_process([
            str(self.runtime_dir / "ffprobe.exe"), "-v", "error", "-protocol_whitelist", "file,pipe", "-select_streams", "a",
            "-show_entries", "stream=index,codec_type,duration:format=duration", "-of", "json", str(source),
        ], "Media inspection", capture_stdout=True)
        try:
            info = json.loads(output)
            streams = info.get("streams", [])
            if not isinstance(streams, list):
                raise ValueError("invalid streams")
            if not streams:
                raise TranscriptionError("This file has no audio track. Select an audio file or a video with sound.")
            durations = [_seconds_to_ms(info.get("format", {}).get("duration"))]
            durations.extend(_seconds_to_ms(stream.get("duration")) for stream in streams)
            return max(durations)
        except (ValueError, TypeError, AttributeError) as exc:
            raise TranscriptionError("The selected media could not be inspected. It may be corrupt or unsupported. Try another file.") from exc

    def _trim_digital_silence(self, audio: Path, emit: Callable[[dict], None]) -> tuple[Path | None, int]:
        """Scan every PCM sample, trimming only long exact-zero outer spans.

        This is not voice detection: even a single nonzero, quiet sample is
        retained. Interior gaps and outer spans under 30 seconds are unchanged.
        The returned offset maps recognized timing back to the original media.
        """
        with wave.open(str(audio), "rb") as wav:
            params = wav.getparams()
            rate = wav.getframerate()
            total_frames = wav.getnframes()
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                return audio, 0  # The normal decode validation owns this error.
            threshold = rate * 30
            if total_frames < threshold:
                return audio, 0
            emit({"kind": "status", "phase": "decoding", "message": "Checking audio for long digital silence…"})
            first = None
            last = None
            scanned = 0
            while True:
                self._check_cancelled()
                data = wav.readframes(262144)
                if not data:
                    break
                nonzero_tail = data.lstrip(b"\0")
                if nonzero_tail:
                    if first is None:
                        first = scanned + (len(data) - len(nonzero_tail)) // 2
                    last = scanned + (len(data.rstrip(b"\0")) - 1) // 2
                scanned += len(data) // 2
            if scanned != total_frames:
                raise TranscriptionError("The prepared audio is incomplete. Retry the media file.")
            if first is None:
                return None, 0
            context = rate // 2
            start = max(0, first - context) if first >= threshold else 0
            end = min(total_frames, last + 1 + context) if total_frames - last - 1 >= threshold else total_frames
            if start == 0 and end == total_frames:
                return audio, 0
            trimmed = audio.with_name("audio-trimmed.wav")
            wav.setpos(start)
            with wave.open(str(trimmed), "wb") as out:
                out.setparams(params)
                remaining = end - start
                while remaining:
                    self._check_cancelled()
                    frames = min(remaining, 262144)
                    out.writeframes(wav.readframes(frames))
                    remaining -= frames
            return trimmed, round(start * 1000 / rate)

    @staticmethod
    def _decode_progress(emit: Callable[[dict], None], duration_ms: int) -> Callable[[str, str], None]:
        last = -1

        def progress(_stream: str, line: str) -> None:
            nonlocal last
            if duration_ms <= 0 or not line.startswith("out_time_us="):
                return
            try:
                percent = min(99, max(0, int(int(line.partition("=")[2]) / (duration_ms * 10))))
            except ValueError:
                return
            if percent > last:
                last = percent
                emit({"kind": "progress", "phase": "decoding", "message": "Preparing audio…", "percent": percent})
        return progress

    @staticmethod
    def _inference_progress(emit: Callable[[dict], None]) -> Callable[[str, str], None]:
        last = -1

        def progress(_stream: str, line: str) -> None:
            nonlocal last
            match = _PERCENT.search(line)
            if match:
                percent = min(99, max(0, int(float(match.group(1)))))
                if percent > last:
                    last = percent
                    emit({"kind": "progress", "phase": "transcribing", "message": "Transcribing on CPU…", "percent": percent})
        return progress

    def _run_process(self, args: list[str], phase: str,
                     on_line: Callable[[str, str], None] | None = None,
                     capture_stdout: bool = False) -> str:
        self._check_cancelled()
        events: queue.Queue[tuple[str, str | None]] = queue.Queue()
        logs: deque[str] = deque(maxlen=16)
        captured: list[str] = []
        captured_size = 0
        flags = 0
        startup = None
        if os.name == "nt":
            flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = subprocess.SW_HIDE
        process = None
        readers: list[threading.Thread] = []

        def read_pipe(name: str, pipe) -> None:
            try:
                for line in pipe:
                    events.put((name, line.rstrip("\r\n")[:8192]))
            finally:
                pipe.close()
                events.put((name, None))

        try:
            with self._process_lock:
                self._check_cancelled()
                process = subprocess.Popen(
                    args, shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                    bufsize=1, cwd=self.runtime_dir, creationflags=flags, startupinfo=startup,
                )
                self._process = process
            for name, pipe in (("stdout", process.stdout), ("stderr", process.stderr)):
                thread = threading.Thread(target=read_pipe, args=(name, pipe), daemon=True)
                readers.append(thread)
                thread.start()
            finished_pipes = 0
            cancelled_at = None
            while finished_pipes < 2 or process.poll() is None:
                if self._cancelled.is_set():
                    if cancelled_at is None:
                        cancelled_at = time.monotonic()
                        if process.poll() is None:
                            try:
                                process.terminate()
                            except OSError:
                                pass
                    elif time.monotonic() - cancelled_at > 2 and process.poll() is None:
                        try:
                            process.kill()
                        except OSError:
                            pass
                try:
                    stream, line = events.get(timeout=0.08)
                except queue.Empty:
                    continue
                if line is None:
                    finished_pipes += 1
                    continue
                if line:
                    logs.append(line[-500:])
                if capture_stdout and stream == "stdout":
                    captured_size += len(line) + 1
                    if captured_size > 1_000_000:
                        raise TranscriptionError("Media inspection returned an unexpectedly large response. Try another media file.")
                    captured.append(line)
                if on_line is not None and not self._cancelled.is_set():
                    on_line(stream, line)
            self._check_cancelled()
            code = process.wait()
            if code != 0:
                detail = _bounded_detail(logs)
                advice = "Check that the file is playable, then retry."
                if phase == "Transcription":
                    advice = "Close other memory-heavy apps and retry. If it persists, restore the verified model in Hisser's data/models folder."
                raise TranscriptionError(f"{phase} failed (exit {code}). {advice}" + (f"\n\n{detail}" if detail else ""))
            return "\n".join(captured)
        finally:
            if process is not None:
                if process.poll() is None:
                    try:
                        process.terminate()
                        process.wait(timeout=2)
                    except (OSError, subprocess.TimeoutExpired):
                        try:
                            process.kill()
                            process.wait(timeout=2)
                        except (OSError, subprocess.TimeoutExpired):
                            pass
                for reader in readers:
                    reader.join(timeout=1)
                with self._process_lock:
                    if self._process is process:
                        self._process = None

    @staticmethod
    def _canonical(raw: dict, source: Path, language: str, duration_ms: int, offset_ms: int = 0) -> dict:
        try:
            transcription = raw["transcription"]
            if not isinstance(transcription, list):
                raise ValueError("invalid transcription")
            segments = []
            previous_start = -1
            for item in transcription:
                offsets = item["offsets"]
                start, end = offsets["from"], offsets["to"]
                text = item["text"]
                if (isinstance(start, bool) or isinstance(end, bool)
                        or not isinstance(start, int) or not isinstance(end, int)
                        or start < 0 or end < start or start < previous_start
                        or not isinstance(text, str) or end + offset_ms > duration_ms + 1000):
                    raise ValueError("invalid transcript segment")
                previous_start = start
                text = text.strip()
                if text:
                    # Whisper occasionally rounds a final endpoint past the audio.
                    segments.append({"start_ms": min(start + offset_ms, duration_ms), "end_ms": min(end + offset_ms, duration_ms), "text": text})
            detected = raw.get("result", {}).get("language", language)
            if not isinstance(detected, str) or not detected:
                detected = language
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise TranscriptionError("Whisper returned invalid transcript timing. Retry the file; no export has been saved.") from exc
        return {
            "schema_version": 1, "source": source.name, "language": detected,
            "duration_ms": duration_ms,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "engine": _ENGINE, "segments": segments,
            "text": "\n".join(segment["text"] for segment in segments),
        }
