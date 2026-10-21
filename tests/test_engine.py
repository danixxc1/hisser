"""Worker integration tests use a synthetic CLI, never the downloaded model.

The subprocesses and cancellation are real; speech recognition is deliberately
stubbed. Actual model/fixture acceptance is recorded separately by setup QA.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import wave

from hisser.engine import Cancelled, Transcriber, TranscriptionError, _cli_argument_path
from hisser.models import ModelSpec


_HELPER = r'''
import json, pathlib, sys, time, wave
runtime = pathlib.Path(__file__).parent
tool, args = sys.argv[1], sys.argv[2:]
config = json.loads((runtime / "scenario.json").read_text())
mode = config.get("mode", "success")
stage = {"ffprobe.exe":"probe", "ffmpeg.exe":"decode", "whisper-cli.exe":"infer"}[tool]
if mode == "hold_" + stage:
    # Only cancellation tests synchronize with these markers. Ordinary retries
    # do not need to reopen a fixture file that Windows may still be scanning.
    (runtime / (stage + ".started")).write_text(str(__import__("os").getpid()))
    print("Started waiting", flush=True)
    time.sleep(30)
if mode == stage + "_error":
    print("Synthetic broken input " + "x" * 5000, file=sys.stderr, flush=True)
    sys.exit(7)
if stage == "probe":
    print(json.dumps({"streams": [] if mode == "no_audio" else [{"index":0,"codec_type":"audio"}], "format":{"duration":"2"}}))
elif stage == "decode":
    print("out_time_us=1000000", flush=True)
    with wave.open(args[-1], "wb") as out:
        out.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        out.writeframes(bytes(16000 * 2 * 2))
elif stage == "infer":
    # Resolve the actual argument paths in the child's cwd, like whisper does.
    # This also catches relative paths calculated for the wrong CPU/CUDA folder.
    model = pathlib.Path(args[args.index("-m") + 1])
    audio = pathlib.Path(args[args.index("-f") + 1])
    assert model.read_bytes().startswith(b"lmgg")
    with wave.open(str(audio), "rb") as prepared:
        assert prepared.getframerate() == 16000
    if mode == "gpu_then_cpu_error" and "-ng" in args:
        print("Synthetic CPU recognition failure", file=sys.stderr, flush=True)
        sys.exit(9)
    if "-ng" not in args:
        if mode in ("gpu_error", "gpu_then_cpu_error"):
            print("CUDA error: out of memory", file=sys.stderr, flush=True)
            sys.exit(8)
        if mode == "gpu_generic_error":
            print("Invalid model header", file=sys.stderr, flush=True)
            sys.exit(7)
        if mode != "gpu_silent_cpu":
            print("whisper_backend_init_gpu: using CUDA0 backend", file=sys.stderr, flush=True)
    print("whisper_print_progress_callback: progress = 20%", file=sys.stderr, flush=True)
    print("whisper_print_progress_callback: progress = 100%", file=sys.stderr, flush=True)
    result = pathlib.Path(args[args.index("-of") + 1] + ".json")
    if mode == "invalid_json":
        result.write_text("not-json")
    else:
        segments = [] if mode == "silence" else [
            {"offsets":{"from":0,"to":1000},"text":"  Kumusta, Mañalac.  "},
            {"offsets":{"from":1000,"to":2000},"text":" Hello, world!"}]
        result.write_text(json.dumps({"result":{"language":"tl"},"transcription":segments}), encoding="utf-8")
'''


class EngineTests(unittest.TestCase):
    def setUp(self):
        # Keep fixtures under the known workspace; Windows app sandbox temp
        # folders can permit creating a directory but deny its descendants.
        self.temp = tempfile.TemporaryDirectory(prefix="hisser-engine-test-", dir=Path(__file__).parent)
        self.root = Path(self.temp.name)
        self.runtime = self.root / "runtime"
        self.runtime.mkdir()
        for name in ("whisper-cli.exe", "ffmpeg.exe", "ffprobe.exe"):
            (self.runtime / name).touch()
        self.helper = self.runtime / "fake_cli.py"
        self.helper.write_text(_HELPER, encoding="utf-8")
        self.model = self.root / "model.bin"
        self.model.write_bytes(b"lmgg" + bytes(124))
        self.model.with_suffix(".bin.metadata.json").write_text(json.dumps({"size":128}), encoding="utf-8")
        self.source = self.root / "Película ni José with spaces.mp4"
        self.source.write_bytes(b"original media is never rewritten")
        self.jobs = self.root / "jobs"
        self.engine = Transcriber(self.runtime, self.model, self.jobs)
        self.events = []
        self.calls = []
        self.children = []
        self.scenario("success")
        original_popen = subprocess.Popen

        def launch(args, **kwargs):
            self.calls.append((args, kwargs))
            child = original_popen([sys.executable, "-u", str(self.helper), Path(args[0]).name, *args[1:]], **kwargs)
            self.children.append(child)
            return child

        self.patcher = patch("hisser.engine.subprocess.Popen", side_effect=launch)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        for child in self.children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
        self.temp.cleanup()

    def scenario(self, mode):
        (self.runtime / "scenario.json").write_text(json.dumps({"mode":mode}), encoding="utf-8")

    def run_job(self):
        return self.engine.run(self.source, "auto", self.events.append)

    def assert_clean(self):
        self.assertTrue(not self.jobs.exists() or not list(self.jobs.iterdir()))
        self.assertTrue(all(child.poll() is not None for child in self.children))
        self.assertEqual(self.source.read_bytes(), b"original media is never rewritten")

    def test_success_canonical_unicode_paths_progress_and_cpu_command(self):
        result = self.run_job()
        self.assertEqual(result["source"], self.source.name)
        self.assertEqual(result["duration_ms"], 2000)
        self.assertEqual(result["language"], "tl")
        self.assertEqual(result["text"], "Kumusta, Mañalac.\nHello, world!")
        self.assertEqual(result["segments"][1], {"start_ms":1000,"end_ms":2000,"text":"Hello, world!"})
        self.assertEqual(result["schema_version"], 1)
        self.assertTrue(result["created_at"].endswith("+00:00"))
        infer = self.calls[-1][0]
        self.assertIn("-ng", infer)
        self.assertIn("-ojf", infer)
        self.assertEqual(infer[infer.index("-t") + 1], "2")
        self.assertEqual(infer[infer.index("-p") + 1], "1")
        self.assertNotIn("-tr", infer)
        self.assertNotIn("-d", infer)
        self.assertNotIn("-ot", infer)
        self.assertTrue(all(call[1]["shell"] is False for call in self.calls))
        self.assertTrue(any(event.get("percent") == 50 and event["phase"] == "decoding" for event in self.events))
        self.assertTrue(any(event.get("percent") == 20 and event["phase"] == "transcribing" for event in self.events))
        self.assertFalse(any(event.get("percent") == 100 or event["phase"] == "complete" for event in self.events))
        self.assert_clean()

    def test_valid_silence_returns_empty_transcript(self):
        self.scenario("silence")
        result = self.run_job()
        self.assertEqual(result["text"], "")
        self.assertEqual(result["segments"], [])
        self.assertEqual(result["duration_ms"], 2000)
        self.assert_clean()

    def test_unicode_portable_folder_uses_resolvable_ascii_recognition_paths(self):
        portable = self.root / "José & Niño"
        new_runtime = portable / "_internal" / "runtime"
        new_runtime.parent.mkdir(parents=True)
        self.runtime.rename(new_runtime)
        self.runtime = new_runtime
        self.helper = self.runtime / "fake_cli.py"
        models = portable / "data" / "models"
        models.mkdir(parents=True)
        new_model = models / self.model.name
        self.model.with_suffix(".bin.metadata.json").rename(new_model.with_suffix(".bin.metadata.json"))
        self.model.rename(new_model)
        self.model = new_model
        self.jobs = portable / "data" / "temp"
        self.add_gpu_runtime()
        for processing, scenario in (("cpu", "success"), ("auto", "success"), ("auto", "gpu_error")):
            with self.subTest(processing=processing, scenario=scenario):
                self.calls.clear()
                self.events.clear()
                self.scenario(scenario)
                self.engine = Transcriber(self.runtime, self.model, self.jobs, processing=processing)
                result = self.run_job()
                self.assertTrue(result["text"])
                recognition = [call for call in self.calls if Path(call[0][0]).name == "whisper-cli.exe"]
                self.assertEqual(len(recognition), 2 if scenario == "gpu_error" else 1)
                for args, options in recognition:
                    paths = [args[args.index(flag) + 1] for flag in ("-m", "-f", "-of")]
                    self.assertTrue(all(path.isascii() and not Path(path).is_absolute() for path in paths))
                    model, audio, output = [(options["cwd"] / path).resolve() for path in paths]
                    self.assertEqual(model, self.model)
                    self.assertEqual(audio.parent.parent, self.jobs)
                    self.assertEqual(output.parent, audio.parent)
                self.assert_clean()

    def test_external_drive_path_keeps_absolute_argument(self):
        path = Path("Z:/external-job/audio.wav")
        with patch("hisser.engine.os.path.relpath", side_effect=ValueError("different drive")):
            self.assertEqual(_cli_argument_path(path, self.runtime), str(path))

    def add_gpu_runtime(self):
        directory = self.runtime / "cuda"
        directory.mkdir(exist_ok=True)
        (directory / "whisper-cli.exe").touch()

    def test_auto_gpu_uses_selected_threads_and_actual_backend_metadata(self):
        self.add_gpu_runtime()
        self.engine = Transcriber(self.runtime, self.model, self.jobs, processing="auto", threads=6)
        result = self.run_job()
        infer = self.calls[-1]
        self.assertEqual(Path(infer[0][0]).parent.name, "cuda")
        self.assertNotIn("-ng", infer[0])
        self.assertEqual(infer[0][infer[0].index("-t") + 1], "6")
        self.assertEqual(infer[1]["cwd"], self.runtime / "cuda")
        self.assertEqual(self.engine.actual_backend, "cuda")
        self.assertIn("NVIDIA CUDA", result["engine"])
        self.assertTrue(any(e.get("backend") == "cuda" and "acceleration" in e["message"] for e in self.events))
        self.assert_clean()

    def test_gpu_memory_failure_retries_once_on_cpu(self):
        self.add_gpu_runtime()
        self.scenario("gpu_error")
        self.engine = Transcriber(self.runtime, self.model, self.jobs, processing="auto", threads=4)
        result = self.run_job()
        infer = [call for call in self.calls if Path(call[0][0]).name == "whisper-cli.exe"]
        self.assertEqual(len(infer), 2)
        self.assertNotIn("-ng", infer[0][0])
        self.assertIn("-ng", infer[1][0])
        self.assertIn("CPU", result["engine"])
        self.assertEqual(len([e for e in self.events if e.get("fallback")]), 1)
        self.assert_clean()

    def test_gpu_generic_model_failure_never_retries(self):
        self.add_gpu_runtime()
        self.scenario("gpu_generic_error")
        self.engine = Transcriber(self.runtime, self.model, self.jobs, processing="auto")
        with self.assertRaisesRegex(TranscriptionError, "Invalid model header"):
            self.run_job()
        self.assertEqual(len([call for call in self.calls if Path(call[0][0]).name == "whisper-cli.exe"]), 1)
        self.assertFalse(any(e.get("fallback") for e in self.events))
        self.assert_clean()

    def test_cancel_while_gpu_fails_never_retries_cpu(self):
        self.add_gpu_runtime()
        self.scenario("gpu_error")
        self.engine = Transcriber(self.runtime, self.model, self.jobs, processing="auto")
        original = self.engine._run_process
        def cancel_after_gpu_failure(args, *a, **kwargs):
            try:
                return original(args, *a, **kwargs)
            except TranscriptionError:
                if Path(args[0]).parent.name == "cuda":
                    self.engine.cancel()
                raise
        with patch.object(self.engine, "_run_process", side_effect=cancel_after_gpu_failure):
            with self.assertRaises(Cancelled):
                self.run_job()
        self.assertEqual(len([call for call in self.calls if Path(call[0][0]).name == "whisper-cli.exe"]), 1)
        self.assertFalse(any(e.get("fallback") for e in self.events))
        self.assert_clean()

    def test_gpu_loader_failures_retry_once_but_other_launch_errors_do_not(self):
        self.add_gpu_runtime()
        for code in (126, 127, 193, 1114, 5):
            with self.subTest(winerror=code):
                self.calls.clear()
                self.events.clear()
                self.engine = Transcriber(self.runtime, self.model, self.jobs, processing="auto")
                error = OSError("Synthetic GPU loader failure")
                error.winerror = code
                original = self.engine._run_process
                launched_gpu = []

                def launch(args, *a, **kwargs):
                    if Path(args[0]).parent.name == "cuda":
                        launched_gpu.append(args)
                        raise error
                    return original(args, *a, **kwargs)

                with patch.object(self.engine, "_run_process", side_effect=launch):
                    if code == 5:
                        with self.assertRaisesRegex(TranscriptionError, "required file"):
                            self.run_job()
                    else:
                        self.assertIn("CPU", self.run_job()["engine"])
                self.assertEqual(len(launched_gpu), 1)
                self.assertEqual(len([e for e in self.events if e.get("fallback")]), int(code != 5))
                self.assert_clean()

    def test_gpu_loader_exit_status_and_dependency_message_retry_once(self):
        self.add_gpu_runtime()
        for message in ("exit -1073741515", "exit 3221225794", "exit -1073741701",
                        "Could not find cublas64_11.dll. Please make sure it is in your library path!"):
            with self.subTest(message=message):
                self.calls.clear()
                self.events.clear()
                self.engine = Transcriber(self.runtime, self.model, self.jobs, processing="auto")
                original = self.engine._run_process

                def launch(args, *a, **kwargs):
                    if Path(args[0]).parent.name == "cuda":
                        raise TranscriptionError(message)
                    return original(args, *a, **kwargs)

                with patch.object(self.engine, "_run_process", side_effect=launch):
                    self.assertIn("CPU", self.run_job()["engine"])
                self.assertEqual(len([e for e in self.events if e.get("fallback")]), 1)
                self.assert_clean()

    def test_cancel_on_fallback_event_stops_before_cpu_launch(self):
        self.add_gpu_runtime()
        self.scenario("gpu_error")
        self.engine = Transcriber(self.runtime, self.model, self.jobs, processing="auto")

        def emit(event):
            self.events.append(event)
            if event.get("fallback"):
                self.engine.cancel()

        with self.assertRaises(Cancelled):
            self.engine.run(self.source, "auto", emit)
        self.assertEqual(len([call for call in self.calls if Path(call[0][0]).name == "whisper-cli.exe"]), 1)
        self.assert_clean()

    def test_cpu_failure_after_gpu_fallback_is_not_retried_or_completed(self):
        self.add_gpu_runtime()
        self.scenario("gpu_then_cpu_error")
        self.engine = Transcriber(self.runtime, self.model, self.jobs, processing="auto")
        with self.assertRaisesRegex(TranscriptionError, "Synthetic CPU recognition failure"):
            self.run_job()
        self.assertEqual(len([call for call in self.calls if Path(call[0][0]).name == "whisper-cli.exe"]), 2)
        self.assertEqual(len([e for e in self.events if e.get("fallback")]), 1)
        self.assert_clean()

    def test_cpu_forced_and_gpu_absent_are_reported_honestly(self):
        for processing, install_gpu in (("cpu", True), ("auto", False)):
            with self.subTest(processing=processing):
                self.calls.clear()
                if install_gpu:
                    self.add_gpu_runtime()
                else:
                    (self.runtime / "cuda" / "whisper-cli.exe").unlink(missing_ok=True)
                self.engine = Transcriber(self.runtime, self.model, self.jobs, processing=processing)
                result = self.run_job()
                self.assertIn("-ng", self.calls[-1][0])
                self.assertIn("CPU", result["engine"])
                self.assert_clean()

    def test_silent_runtime_cpu_fallback_is_not_mislabeled_gpu(self):
        self.add_gpu_runtime()
        self.scenario("gpu_silent_cpu")
        self.engine = Transcriber(self.runtime, self.model, self.jobs, processing="auto")
        result = self.run_job()
        self.assertEqual(self.engine.actual_backend, "cpu")
        self.assertIn("CPU", result["engine"])
        self.assertFalse(any(e.get("kind") == "progress" and e.get("backend") == "cuda" for e in self.events))
        self.assert_clean()

    def test_cancel_before_first_run_is_retained_and_retry_works(self):
        self.engine.cancel()
        with self.assertRaises(Cancelled):
            self.run_job()
        self.assertEqual(self.calls, [])
        self.assertIn("Kumusta", self.run_job()["text"])
        self.assert_clean()

    def test_missing_source_model_runtime_and_invalid_language(self):
        with self.assertRaisesRegex(TranscriptionError, "selected file is missing"):
            self.engine.run(self.root / "gone.mp4", "auto", self.events.append)
        with self.assertRaisesRegex(TranscriptionError, "supported"):
            self.engine.run(self.source, "invalid-language", self.events.append)
        self.model.unlink()
        with self.assertRaisesRegex(TranscriptionError, "model is missing"):
            self.run_job()
        self.model.write_bytes(b"lmgg" + bytes(124))
        (self.runtime / "ffprobe.exe").unlink()
        with self.assertRaisesRegex(TranscriptionError, "ffprobe.exe"):
            self.run_job()
        self.assertEqual(self.calls, [])

    def test_corrupt_truncated_and_bad_metadata_models_are_rejected_before_spawn(self):
        for model_data, metadata, expected in (
            (b"GGUF" + bytes(124), {"size":128}, "corrupt"),
            (b"lmgg" + bytes(70), {"size":128}, "incomplete"),
            (b"lmgg" + bytes(124), {"size":True}, "verification record"),
        ):
            with self.subTest(expected=expected):
                self.model.write_bytes(model_data)
                self.model.with_suffix(".bin.metadata.json").write_text(json.dumps(metadata))
                with self.assertRaisesRegex(TranscriptionError, expected):
                    self.run_job()
        self.assertEqual(self.calls, [])

    def test_known_model_requires_matching_filename_size_and_sha_metadata(self):
        # Patch the catalog lookup with a small pinned fixture; no large model or
        # model download is needed to exercise production descriptor validation.
        spec = ModelSpec("fixture-q5", "verified-fixture.bin", "Verified fixture", 128, "a" * 64)
        self.model = self.root / spec.filename
        self.model.write_bytes(b"lmgg" + bytes(124))
        record = self.model.with_suffix(".bin.metadata.json")
        with patch("hisser.engine.model_for_filename", return_value=spec):
            self.engine = Transcriber(self.runtime, self.model, self.jobs)
        for metadata in (None, {"size":128}, {"size":128, "sha256":"b" * 64},
                         {"size":127, "sha256":spec.sha256}):
            with self.subTest(metadata=metadata):
                if metadata is None:
                    record.unlink(missing_ok=True)
                else:
                    record.write_text(json.dumps(metadata), encoding="utf-8")
                with self.assertRaisesRegex(TranscriptionError, "verification record"):
                    self.run_job()
        self.assertEqual(self.calls, [])
        record.write_text(json.dumps({"size":128, "sha256":spec.sha256}), encoding="utf-8")
        result = self.run_job()
        self.assertIn("fixture-q5", result["engine"])
        self.assert_clean()

        self.calls.clear()
        self.model.write_bytes(b"lmgg" + bytes(125))
        with self.assertRaisesRegex(TranscriptionError, "selected verified transcription profile"):
            self.run_job()
        wrong_name = self.root / "wrong-model.bin"
        wrong_name.write_bytes(b"lmgg" + bytes(124))
        self.engine = Transcriber(self.runtime, wrong_name, self.jobs, model_spec=spec)
        with self.assertRaisesRegex(TranscriptionError, "selected verified transcription profile"):
            self.run_job()
        self.assertEqual(self.calls, [])

    def test_model_is_never_read_during_engine_construction(self):
        with patch("pathlib.Path.open", side_effect=AssertionError("model opened at startup")):
            engine = Transcriber(self.runtime, self.model, self.jobs)
        self.assertIsNone(engine._process)
        self.assertEqual(self.calls, [])

    def test_no_audio_corrupt_media_inference_failure_and_retry(self):
        for mode, expected in (("no_audio", "no audio track"), ("probe_error", "Media inspection failed"),
                               ("decode_error", "Audio preparation failed"), ("infer_error", "Transcription failed"),
                               ("invalid_json", "readable transcript")):
            with self.subTest(mode=mode):
                self.scenario(mode)
                with self.assertRaisesRegex(TranscriptionError, expected) as caught:
                    self.run_job()
                self.assertLess(len(str(caught.exception)), 2400)
                self.assert_clean()
        self.scenario("success")
        self.assertIn("Kumusta", self.run_job()["text"])
        self.assert_clean()

    def test_cancel_each_owned_stage_is_prompt_and_allows_retry(self):
        for stage in ("probe", "decode", "infer"):
            with self.subTest(stage=stage):
                for marker in self.runtime.glob("*.started"):
                    marker.unlink()
                self.scenario("hold_" + stage)
                outcome = []

                def run():
                    try:
                        outcome.append(self.run_job())
                    except Exception as exc:
                        outcome.append(exc)

                worker = threading.Thread(target=run)
                worker.start()
                deadline = time.monotonic() + 8
                marker = self.runtime / (stage + ".started")
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(marker.exists(), f"{stage} did not start")
                started = time.monotonic()
                self.engine.cancel()
                self.assertLess(time.monotonic() - started, 0.5)
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
                self.assertEqual(len(outcome), 1)
                self.assertIsInstance(outcome[0], Cancelled)
                self.assert_clean()
                self.scenario("success")
                self.assertIn("Kumusta", self.run_job()["text"])
                self.assert_clean()

    def test_unrelated_child_survives_cancellation(self):
        # Launch outside the patched Popen so it is never owned by this engine.
        self.patcher.stop()
        unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                     creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        self.patcher.start()
        try:
            self.engine.cancel()
            self.assertIsNone(unrelated.poll())
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=5)

    def test_parallel_run_rejected_and_callback_failure_cleans_child(self):
        self.engine._run_lock.acquire()
        try:
            with self.assertRaisesRegex(TranscriptionError, "already running"):
                self.run_job()
        finally:
            self.engine._run_lock.release()

        def broken_callback(event):
            if event["kind"] == "progress":
                raise RuntimeError("UI event receiver failed")

        with self.assertRaisesRegex(RuntimeError, "event receiver"):
            self.engine.run(self.source, "en", broken_callback)
        self.assert_clean()
        self.assertIn("Kumusta", self.run_job()["text"])

    def test_long_timing_has_no_thirty_minute_cap_and_invalid_timing_rejected(self):
        raw = {"result":{"language":"en"}, "transcription":[
            {"offsets":{"from":1_850_000,"to":1_855_000}, "text":"Speech after minute thirty."}]}
        result = Transcriber._canonical(raw, self.source, "en", 1_900_000)
        self.assertEqual(result["segments"][0]["start_ms"], 1_850_000)
        self.assertIn("Speech after minute thirty.", result["text"])
        for start, end in ((-1, 5), (500, 100), (True, 100), (0, 10_000_000)):
            raw["transcription"][0]["offsets"] = {"from":start,"to":end}
            with self.assertRaisesRegex(TranscriptionError, "invalid transcript timing"):
                Transcriber._canonical(raw, self.source, "en", 1_900_000)

    def write_pcm(self, name, data):
        path = self.root / name
        with wave.open(str(path), "wb") as wav:
            wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            wav.writeframes(data)
        return path

    def test_exact_outer_silence_trim_retains_quiet_samples_context_and_rounds_offset(self):
        leading_frames = 481234
        quiet = b"\x00\x01\x01\x00"  # Nonzero +256 and +1 samples, never a threshold.
        pcm = bytes(leading_frames * 2) + quiet + bytes(31 * 16000 * 2)
        path = self.write_pcm("outer-silence.wav", pcm)
        trimmed, offset = self.engine._trim_digital_silence(path, self.events.append)
        self.assertNotEqual(trimmed, path)
        self.assertEqual(offset, round((leading_frames - 8000) * 1000 / 16000))
        with wave.open(str(trimmed), "rb") as wav:
            self.assertEqual(wav.getnframes(), 16002)
            self.assertEqual(wav.readframes(wav.getnframes()), bytes(8000 * 2) + quiet + bytes(8000 * 2))
        self.assertEqual(path.read_bytes()[44:], pcm)
        raw = {"transcription":[{"offsets":{"from":500,"to":501},"text":"Quiet word"}]}
        full_duration = round((leading_frames + 2 + 31 * 16000) * 1000 / 16000)
        result = Transcriber._canonical(raw, self.source, "en", full_duration, offset_ms=offset)
        self.assertEqual(result["duration_ms"], full_duration)
        self.assertEqual(result["segments"][0]["start_ms"], offset + 500)

    def test_short_outer_gaps_and_long_interior_silence_are_unchanged(self):
        for name, pcm in (
            ("short-outer.wav", bytes(20 * 16000 * 2) + b"\x01\x00" + bytes(20 * 16000 * 2)),
            ("long-interior.wav", b"\x01\x00" + bytes(31 * 16000 * 2) + b"\x00\x80"),
        ):
            with self.subTest(name=name):
                path = self.write_pcm(name, pcm)
                actual, offset = self.engine._trim_digital_silence(path, self.events.append)
                self.assertEqual(actual, path)
                self.assertEqual(offset, 0)
                with wave.open(str(path), "rb") as wav:
                    self.assertEqual(wav.readframes(wav.getnframes()), pcm)

    def test_all_zero_long_audio_is_empty_but_short_silence_still_uses_engine(self):
        for seconds, expected_none in ((30, True), (29, False)):
            with self.subTest(seconds=seconds):
                path = self.write_pcm(f"zero-{seconds}.wav", bytes(seconds * 16000 * 2))
                actual, offset = self.engine._trim_digital_silence(path, self.events.append)
                self.assertEqual(actual is None, expected_none)
                self.assertEqual(offset, 0)

    def test_silence_scan_honors_cancellation(self):
        path = self.write_pcm("cancel-scan.wav", bytes(31 * 16000 * 2))
        def cancel_on_scan(event):
            self.engine.cancel()
        with self.assertRaises(Cancelled):
            self.engine._trim_digital_silence(path, cancel_on_scan)


if __name__ == "__main__":
    unittest.main()
