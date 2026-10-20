"""Serial, local-only speed comparisons; media and reports stay under ignored qa/.

This runner does not change the installed app or choose a model for the user.
Raw whisper.cpp arguments retain the normal recognition quality defaults.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import difflib
from functools import lru_cache
import hashlib
import html
import json
import os
from pathlib import Path
import queue
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
import wave

import psutil

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PORTABLE = ROOT / "dist/Hisser"
FILM_OFFSETS = (300, 2800, 5100)
CLIP_SECONDS = 30
TIMEOUT_SECONDS = 600
DECODING_PROFILE = {"processors": 1, "beam_size": 5, "best_of": 5, "translate": False,
                    "vad": False, "temperature": 0.0, "temperature_increment": 0.2,
                    "no_speech_threshold": 0.6, "flash_attention": True}


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def flags():
    return subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0


@lru_cache(maxsize=16)
def cached_sha256(path: str, size: int, modified_ns: int) -> str:
    """Avoid rereading a GB model per clip, while detecting a replaced input file."""
    return sha256(Path(path))


def file_sha256(path: Path) -> str:
    stat = path.stat()
    return cached_sha256(str(path.resolve()), stat.st_size, stat.st_mtime_ns)


def measurement_matches(report, identity):
    if not report.get("success") or report.get("cancelled"):
        return False
    if not all(report.get(key) == value for key, value in identity.items()):
        return False
    return (identity["backend_requested"] != "cuda" or
            any(re.search(r"using CUDA\d+ backend", line, re.I) for line in report.get("gpu_log_evidence", [])))


def ensure_idle():
    for process in psutil.process_iter(["name", "pid"]):
        try:
            if (process.info["name"] or "").lower() == "whisper-cli.exe":
                raise RuntimeError(f"A whisper-cli process is already running (PID {process.pid}). Wait for it; no process was stopped.")
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue


def audio_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes() / wav.getframerate()


def prepare(args):
    out = args.output_directory
    out.mkdir(parents=True, exist_ok=True)
    source_hash_before = sha256(args.film)
    prior_manifest_path = out / "fixtures.json"
    prior_manifest = json.loads(prior_manifest_path.read_text(encoding="utf-8")) if prior_manifest_path.is_file() else {}
    if prior_manifest and prior_manifest.get("film_sha256_before") != source_hash_before:
        raise RuntimeError("This output directory belongs to a different source. Select a fresh --output-directory; existing evidence was preserved.")
    prior_clips = {c["id"]: c for c in prior_manifest.get("clips", [])}
    ffmpeg = args.cpu_runtime / "ffmpeg.exe"
    if not ffmpeg.is_file():
        raise FileNotFoundError(ffmpeg)
    entries = []
    for index, offset in enumerate(FILM_OFFSETS, 1):
        destination = out / "clips" / f"film-{index}-{offset}s.wav"
        destination.parent.mkdir(exist_ok=True)
        if destination.exists() and (prior_clips.get(f"film-{index}", {}).get("sha256") != sha256(destination)):
            raise RuntimeError("Existing excerpt cannot be verified against its source manifest. Select a fresh --output-directory.")
        if not destination.exists():
            subprocess.run([str(ffmpeg), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                            "-protocol_whitelist", "file,pipe", "-ss", str(offset), "-i", str(args.film),
                            "-t", str(CLIP_SECONDS), "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
                            str(destination)], check=True, capture_output=True, creationflags=flags(), timeout=60)
        if abs(audio_duration(destination) - CLIP_SECONDS) > 0.1:
            raise RuntimeError(f"Excerpt {index} is not a complete {CLIP_SECONDS}-second recording. Check source duration and offsets.")
        entries.append({"id": f"film-{index}", "path": str(destination.resolve()), "source_offset_seconds": offset,
                        "duration_seconds": audio_duration(destination), "sha256": sha256(destination),
                        "synthetic": False, "spoken_content_human_verified": False})
    english = out / "clips" / "english-known-14s.wav"
    if not english.exists():
        subprocess.run([str(ffmpeg), "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(args.english),
                        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(english)], check=True,
                       capture_output=True, creationflags=flags(), timeout=60)
    source_hash_after = sha256(args.film)
    manifest = {"film_source": str(args.film), "film_sha256_before": source_hash_before,
                "film_sha256_after": source_hash_after,
                "film_source_unchanged": source_hash_after == source_hash_before,
                "source_preservation_status": "Original source SHA-256 checked before and after fixture preparation.",
                "clips": entries,
                "english": {"id": "english", "path": str(english.resolve()), "synthetic": True,
                            "duration_seconds": audio_duration(english), "sha256": sha256(english)},
                "privacy": "Local-only film excerpts/transcripts; never include qa/ in GitHub."}
    write_json(out / "fixtures.json", manifest)
    if not manifest["film_source_unchanged"]:
        raise RuntimeError("Source SHA-256 changed during preparation. Evidence is retained; comparison must not proceed.")
    print(json.dumps({"prepared": len(entries), "output": str(out)}, ensure_ascii=False), flush=True)
    return manifest


def gpu_sample(smi: str | None):
    if not smi:
        return None
    try:
        result = subprocess.run([smi, "--query-gpu=memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
                                text=True, capture_output=True, creationflags=flags(), timeout=3)
        fields = result.stdout.splitlines()[0].split(",")
        return {"memory_used_mib": int(fields[0].strip()), "utilization_percent": int(fields[1].strip())}
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None


def recognize(args, label: str, source: Path, model: Path, backend: str, threads: int, language: str):
    output = args.output_directory
    report_path = output / "runs" / (label + ".json")
    cli = (args.cuda_runtime if backend == "cuda" else args.cpu_runtime) / "whisper-cli.exe"
    if not cli.is_file() or not model.is_file():
        raise FileNotFoundError(f"Required CLI/model not ready: {cli} / {model}")
    identity = {"source_sha256": file_sha256(source), "threads": threads, "model_file": model.name,
                "model_sha256": file_sha256(model), "cli_sha256": file_sha256(cli),
                "backend_requested": backend, "language": language, "decoding_profile": DECODING_PROFILE}
    if report_path.is_file() and not args.rerun:
        previous = json.loads(report_path.read_text(encoding="utf-8"))
        if measurement_matches(previous, identity):
            return previous
    if args.reuse_from and not args.rerun:
        prior_path = args.reuse_from / "runs" / (label + ".json")
        if prior_path.is_file():
            prior = json.loads(prior_path.read_text(encoding="utf-8"))
            if measurement_matches(prior, identity):
                reused = dict(prior)
                reused["source"] = str(source)
                reused["reuse_provenance"] = {
                    "report": str(prior_path.resolve()), "measured_source": prior["source"],
                    "linked_utc": datetime.now(timezone.utc).isoformat(),
                    "reason": "New prepared audio SHA-256 exactly matches the previously measured PCM fixture; recognition was not rerun."
                }
                write_json(report_path, reused)
                print(json.dumps({"event": "reused_identical_audio", "job": label, "wall_seconds": prior["wall_seconds"]}), flush=True)
                return reused
    ensure_idle()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_stem = output / "transcripts" / label
    transcript_stem.parent.mkdir(parents=True, exist_ok=True)
    command = [str(cli), "-m", str(model), "-f", str(source), "-l", language, "-t", str(threads), "-p", "1",
               "-bs", "5", "-bo", "5", "-pp", "-ojf", "-of", str(transcript_stem)]
    if backend == "cpu":
        command.append("-ng")
    smi = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/nvidia-smi.exe")
    if not Path(smi).is_file():
        smi = shutil.which("nvidia-smi")
    baseline = gpu_sample(smi)
    start = time.monotonic()
    lines: list[str] = []
    messages: queue.Queue[str | None] = queue.Queue()
    peak_rss = 0
    peak_gpu = baseline["memory_used_mib"] if baseline else None
    peak_util = 0
    first_processing = None
    next_sample = start
    next_status = start
    process = None
    error = None
    cancelled = False
    log_path = output / "runs" / (label + ".log")
    raw = None
    priority = None
    print(json.dumps({"event": "start", "job": label, "backend": backend, "threads": threads,
                      "duration_seconds": audio_duration(source)}, ensure_ascii=False), flush=True)
    try:
        process = subprocess.Popen(command, cwd=cli.parent, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                   creationflags=flags(), bufsize=1)
        managed = psutil.Process(process.pid)
        try:
            priority = int(managed.nice())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        def read():
            try:
                for line in process.stdout:
                    messages.put(line.rstrip("\r\n"))
            finally:
                messages.put(None)
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        ended = False
        with log_path.open("w", encoding="utf-8") as log:
            while process.poll() is None or not ended:
                now = time.monotonic()
                if now - start > TIMEOUT_SECONDS:
                    raise TimeoutError(f"Controlled benchmark exceeded {TIMEOUT_SECONDS} seconds.")
                if args.cancel_after and now - start >= args.cancel_after:
                    cancelled = True
                    process.terminate()
                    args.cancel_after = None
                try:
                    line = messages.get(timeout=0.1)
                    if line is None:
                        ended = True
                    else:
                        log.write(line + "\n")
                        log.flush()
                        lines.append(line)
                        if first_processing is None and "main: processing" in line:
                            first_processing = round(now - start, 3)
                except queue.Empty:
                    pass
                try:
                    peak_rss = max(peak_rss, managed.memory_info().rss)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                if now >= next_sample:
                    sample = gpu_sample(smi)
                    if sample:
                        peak_gpu = max(peak_gpu or 0, sample["memory_used_mib"])
                        peak_util = max(peak_util, sample["utilization_percent"])
                    next_sample = time.monotonic() + 1
                if now >= next_status:
                    write_json(output / "status.json", {"state": "running", "job": label, "backend": backend, "threads": threads,
                               "elapsed_seconds": round(now - start, 2), "peak_rss_bytes": peak_rss,
                               "overall_gpu_used_peak_mib": peak_gpu})
                    next_status = now + 5
            code = process.wait()
        if code != 0:
            error = {"type": "cancelled" if cancelled else "process_exit", "exit_code": code, "detail": "\n".join(lines[-20:])}
        else:
            raw = json.loads(transcript_stem.with_suffix(".json").read_text(encoding="utf-8-sig"))
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            cancelled = True
        error = {"type": type(exc).__name__, "message": str(exc)}
        if isinstance(exc, KeyboardInterrupt):
            raise
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
    elapsed = time.monotonic() - start
    joined = "\n".join(lines)
    timing = {}
    for key, value in re.findall(r"whisper_print_timings:\s*([a-z_ ]+?)\s*=\s*([\d.]+)\s*ms", joined):
        timing[key.strip().replace(" ", "_") + "_ms"] = float(value)
    text = "\n".join(item["text"].strip() for item in raw.get("transcription", []) if item.get("text", "").strip()) if raw else None
    gpu_evidence = [line for line in lines if re.search(r"CUDA\d|CUDA:|CUDA devices|using CUDA|ggml_cuda_init|device.*CUDA", line, re.I)]
    gpu_confirmed = any(re.search(r"using CUDA\d+ backend", line, re.I) for line in gpu_evidence)
    if backend == "cuda" and raw is not None and error is None and not gpu_confirmed:
        error = {"type": "gpu_not_confirmed", "message": "Transcript exists, but the log does not confirm recognition used a CUDA backend."}
    result = {**identity, "label": label, "success": raw is not None and error is None, "cancelled": cancelled,
              "completed_utc": datetime.now(timezone.utc).isoformat(), "backend_requested": backend,
              "threads": threads, "language": language, "model_file": model.name, "source": str(source),
              "source_sha256": sha256(source), "duration_seconds": audio_duration(source),
              "wall_seconds": round(elapsed, 3), "startup_to_processing_seconds": first_processing,
              "cli_timings": timing, "peak_rss_bytes": peak_rss, "priority_class": priority,
              "overall_gpu_baseline_used_mib": baseline["memory_used_mib"] if baseline else None,
              "overall_gpu_peak_used_mib": peak_gpu, "overall_gpu_peak_utilization_percent": peak_util,
              "gpu_memory_note": "Whole GPU usage includes other apps; not exact per-process VRAM on Windows WDDM.",
              "gpu_log_evidence": gpu_evidence, "gpu_backend_confirmed": gpu_confirmed,
              "recognized_text": text, "error": error,
              "transcript_json": str(transcript_stem.with_suffix(".json")) if raw else None}
    write_json(report_path, result)
    write_json(output / "status.json", {"state": "finished", "job": label, "backend": backend, "threads": threads,
               "elapsed_seconds": result["wall_seconds"], "success": result["success"],
               "peak_rss_bytes": peak_rss, "overall_gpu_used_peak_mib": peak_gpu})
    print(json.dumps({"event": "finished", "job": label, "success": result["success"], "wall_seconds": result["wall_seconds"],
                      "peak_rss_bytes": peak_rss, "gpu_peak_mib": peak_gpu, "error": error}, ensure_ascii=False), flush=True)
    return result


def choose_threads(results):
    successful = [r for r in results if r["success"]]
    if len(successful) != 4:
        raise RuntimeError("All four CPU thread settings must complete before selecting a winner.")
    best = min(r["wall_seconds"] for r in successful)
    eligible = [r for r in successful if r["wall_seconds"] <= best * 1.05]
    return min(r["threads"] for r in eligible)


def thread_runs(args, manifest):
    source = Path(manifest["english"]["path"])
    results = [recognize(args, f"threads-large-cpu-{n}", source, args.large_model, "cpu", n, "en") for n in (2, 4, 6, 8)]
    winner = choose_threads(results)
    summary = {"chosen_threads": winner, "selection_rule": "Fewest threads within 5% of fastest CLI wall time",
               "runs": results, "fixture": "Same synthetic English PCM16 recording, separate cold CLI/model start per run"}
    write_json(args.output_directory / "threads.json", summary)
    print(json.dumps({"chosen_threads": winner}), flush=True)
    return winner


def matrix_runs(args, manifest):
    selected = args.threads
    threads_path = args.output_directory / "threads.json"
    if selected is None and threads_path.exists():
        selected = json.loads(threads_path.read_text(encoding="utf-8"))["chosen_threads"]
    if selected is None:
        raise RuntimeError("Run threads first, or specify --threads explicitly.")
    results = []
    configurations = [("large-cpu", args.large_model, "cpu"), ("large-cuda", args.large_model, "cuda"),
                      ("turbo-cpu", args.turbo_model, "cpu"), ("turbo-cuda", args.turbo_model, "cuda")]
    for config, model, backend in configurations:
        if args.config and config not in args.config:
            continue
        english = manifest["english"]
        results.append(recognize(args, f"{config}-english", Path(english["path"]), model, backend, selected, "en"))
        for clip in manifest["clips"]:
            if sha256(Path(clip["path"])) != clip["sha256"]:
                raise RuntimeError(f"Prepared fixture changed: {clip['id']}. Do not compare different audio.")
            results.append(recognize(args, f"{config}-{clip['id']}", Path(clip["path"]), model, backend, selected, "tl"))
    source = Path(manifest["film_source"])
    if source.is_file():
        manifest["film_sha256_after"] = sha256(source)
        manifest["film_source_unchanged"] = manifest["film_sha256_after"] == manifest["film_sha256_before"]
        manifest["source_preservation_status"] = "Original source SHA-256 compared with preparation hash."
    else:
        manifest["film_sha256_after"] = None
        manifest["film_source_unchanged"] = None
        manifest["source_preservation_status"] = "Original source is unavailable (user deleted it); only retained, previously prepared clip hashes can be checked."
    manifest["prepared_clips_unchanged"] = all(sha256(Path(c["path"])) == c["sha256"] for c in manifest["clips"])
    write_json(args.output_directory / "fixtures.json", manifest)
    all_results = [json.loads(p.read_text(encoding="utf-8")) for p in (args.output_directory / "runs").glob("*.json")]
    write_json(args.output_directory / "matrix.json", {"threads": selected,
               "results": [r for r in all_results if not r["label"].startswith("threads-")],
               "source_unchanged": manifest["film_source_unchanged"],
               "source_preservation_status": manifest["source_preservation_status"],
               "prepared_clips_unchanged": manifest["prepared_clips_unchanged"], "human_accuracy_approved": False})
    return results


def render_report(args):
    out = args.output_directory
    manifest = json.loads((out / "fixtures.json").read_text(encoding="utf-8"))
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in (out / "runs").glob("*.json")]
    by_label = {r["label"]: r for r in runs}
    rows = []
    review_note = ("Comparison excerpts prepared from the provided video. Accuracy still awaits your listening approval."
                   if Path(manifest["film_source"]).is_file() else
                   "Preliminary speed checks on retained excerpts. Final accuracy review awaits the replacement source video.")
    reuse_note = ("Timings were reused only after verifying identical prepared PCM audio SHA-256, model, backend, language and thread setting. Recognition was not rerun."
                  if any(r.get("reuse_provenance") for r in runs) else "Each timing records an actual recognition process on this fixture.")
    md = ["# Hisser speed and Tagalog comparison", "", "Local-only private film excerpts. **Accuracy needs your listening review.** Model agreement is not proof of correctness.", "",
          review_note, "", reuse_note, "",
          manifest.get("source_preservation_status", "Original source preservation has not yet been rechecked."), "",
          "All configurations use the same PCM audio, original-language transcription and ordinary decoding defaults (beam size 5, best of 5).", "", "| Configuration | Median 30 s clip time | Peak process RAM | Peak whole-GPU memory |", "|---|---:|---:|---:|"]
    for config in ("large-cpu", "large-cuda", "turbo-cpu", "turbo-cuda"):
        group = [r for r in runs if r["label"].startswith(config + "-film-")]
        ok = [r for r in group if r["success"]]
        median = round(statistics.median(r["wall_seconds"] for r in ok), 3) if ok else None
        rss = max((r["peak_rss_bytes"] for r in ok), default=0)
        gpu = max((r["overall_gpu_peak_used_mib"] or 0 for r in ok), default=0)
        rows.append({"configuration": config, "successful_clips": len(ok), "median_wall_seconds": median,
                     "peak_rss_bytes": rss, "peak_whole_gpu_used_mib": gpu})
        timing_label = f"{median} s" if median is not None else ("FAILED" if group else "Not run yet")
        md.append(f"| {config} | {timing_label} ({len(ok)}/3 passed) | {rss/1e9:.2f} GB | {gpu} MiB |")
    md += ["", "Whole-GPU memory includes other programs and is not an exact per-process measurement.", "",
           "## Listen and compare", "", "For each excerpt, check names, omitted dialogue and changes in meaning. Turbo will not be promoted until you approve its wording.", ""]
    sections = []
    for clip in manifest["clips"]:
        a = by_label.get("large-cuda-" + clip["id"]) or by_label.get("large-cpu-" + clip["id"], {})
        b = by_label.get("turbo-cuda-" + clip["id"]) or by_label.get("turbo-cpu-" + clip["id"], {})
        if not a.get("success"):
            a = by_label.get("large-cpu-" + clip["id"], {})
        if not b.get("success"):
            b = by_label.get("turbo-cpu-" + clip["id"], {})
        relative = Path(clip["path"]).relative_to(out.resolve()).as_posix()
        large_text = a.get("recognized_text") or "No successful transcript."
        turbo_text = b.get("recognized_text") or "No successful transcript."
        large_label = "Current large-v3 · " + a.get("backend_requested", "pending").upper()
        turbo_label = "Turbo · " + b.get("backend_requested", "pending").upper()
        ratio = difflib.SequenceMatcher(None, large_text.casefold().split(), turbo_text.casefold().split()).ratio()
        offset = clip["source_offset_seconds"]
        md += [f"### {clip['id']} — source {offset//60:02}:{offset%60:02} to {(offset+CLIP_SECONDS)//60:02}:{(offset+CLIP_SECONDS)%60:02}", "",
               f"[Play the 30-second excerpt]({relative})", "", f"**{large_label}:**", "", large_text, "", f"**{turbo_label}:**", "", turbo_text, "",
               f"Word-sequence similarity: {ratio:.0%} (comparison only; not an accuracy score).", ""]
        cpu_sections = []
        for config in ("large-cpu", "turbo-cpu"):
            cpu = by_label.get(config + "-" + clip["id"], {})
            if cpu.get("success"):
                md += [f"**{config} reference:**", "", cpu["recognized_text"], ""]
                cpu_sections.append(f"<article><h3>{html.escape(config)}</h3><p>{html.escape(cpu['recognized_text'])}</p></article>")
        cpu_details = "<details><summary>Show CPU reference transcripts</summary><div class='compare'>" + "".join(cpu_sections) + "</div></details>" if cpu_sections else ""
        sections.append(f"<section><h2>{html.escape(clip['id'])} · source {offset//60:02}:{offset%60:02}–{(offset+CLIP_SECONDS)//60:02}:{(offset+CLIP_SECONDS)%60:02}</h2><audio controls preload='none' src='{html.escape(relative, quote=True)}'></audio><div class='compare'><article><h3>{html.escape(large_label)}</h3><p>{html.escape(large_text)}</p></article><article><h3>{html.escape(turbo_label)}</h3><p>{html.escape(turbo_text)}</p></article></div><p class='note'>Word-sequence similarity {ratio:.0%}; this is not an accuracy score.</p>{cpu_details}</section>")
    (out / "COMPARE.md").write_text("\n".join(md), encoding="utf-8")
    page = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Hisser listening comparison</title><style>body{font:17px/1.6 'Segoe UI',sans-serif;background:#edf2ee;color:#192d23;margin:0;padding:30px;max-width:1100px;margin:auto}h1{line-height:1.2}section{margin-top:36px;padding-top:20px;border-top:1px solid #b8c8bd}.compare{display:grid;grid-template-columns:1fr 1fr;gap:24px}article{background:white;padding:18px}p{white-space:pre-wrap}h3{margin-top:0}.note{font-size:14px;color:#4e6256}audio{width:min(100%,600px)}@media(max-width:700px){.compare{grid-template-columns:1fr}body{padding:18px}}</style><h1>Hisser: listen and compare</h1><p>These clips stay on your computer. Compare the wording with the audio, especially names, missing dialogue and changes in meaning. Turbo is awaiting your approval.</p>""" + "".join(sections) + "</html>"
    provenance = "<p class='note'>" + html.escape(review_note) + "</p><p class='note'>" + html.escape(reuse_note) + "</p>"
    page = page.replace("</html>", provenance + "</html>")
    (out / "COMPARE.html").write_text(page, encoding="utf-8")
    write_json(out / "summary.json", {"configurations": rows, "human_accuracy_approved": False,
                "film_source_unchanged": manifest.get("film_source_unchanged"),
                "source_preservation_status": manifest.get("source_preservation_status"),
                "reuse_note": reuse_note, "comparison_html": str((out / "COMPARE.html").resolve())})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "threads", "matrix", "report", "all"))
    parser.add_argument("--portable", type=Path, default=DEFAULT_PORTABLE)
    parser.add_argument("--cpu-runtime", type=Path)
    parser.add_argument("--cuda-runtime", type=Path, default=ROOT / "runtime/cuda")
    parser.add_argument("--large-model", type=Path)
    parser.add_argument("--turbo-model", type=Path, default=ROOT / "qa/speed-models/ggml-large-v3-turbo-q5_0.bin")
    parser.add_argument("--film", type=Path, required=False)
    parser.add_argument("--english", type=Path, default=ROOT / "qa/engine-integration/José Mañalac - synthetic fixtures/Prueba ni José - clear English.wav")
    parser.add_argument("--output-directory", type=Path, default=ROOT / "qa/speed")
    parser.add_argument("--threads", type=int, choices=(2, 4, 6, 8))
    parser.add_argument("--config", action="append", choices=("large-cpu", "large-cuda", "turbo-cpu", "turbo-cuda"),
                        help="Repeat to run selected configurations; successful prior results are reused.")
    parser.add_argument("--rerun", action="store_true")
    parser.add_argument("--reuse-from", type=Path, help="Link previous measurements only when prepared PCM hashes and recognition configuration match.")
    parser.add_argument("--cancel-after", type=float)
    args = parser.parse_args()
    args.output_directory = args.output_directory.resolve()
    args.cpu_runtime = (args.cpu_runtime or args.portable / "_internal/runtime").resolve()
    args.cuda_runtime = args.cuda_runtime.resolve()
    args.large_model = (args.large_model or args.portable / "data/models/ggml-large-v3-q5_0.bin").resolve()
    args.turbo_model = args.turbo_model.resolve()
    args.output_directory.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_directory / "fixtures.json"
    if args.phase in ("prepare", "all") or not manifest_path.is_file():
        if not args.film:
            parser.error("--film is required when preparing fixtures for the first time")
        manifest = prepare(args)
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if args.phase in ("threads", "all"):
        args.threads = thread_runs(args, manifest)
    if args.phase in ("matrix", "all"):
        matrix_runs(args, manifest)
    if args.phase in ("report", "all"):
        render_report(args)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
