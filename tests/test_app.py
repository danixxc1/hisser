"""Native Tk state tests. All windows stay withdrawn; no inference is launched."""
from __future__ import annotations

import json
from pathlib import Path
import tkinter as tk

import pytest

from hisser import app as app_module

pytestmark = pytest.mark.usefixtures("tk_main_thread_cleanup")


class DeferredThread:
    """Run a UI-owned worker only when a test explicitly releases it."""

    created = []

    def __init__(self, target, **_kwargs):
        self.target = target
        self.started = False
        self.created.append(self)

    def start(self):
        self.started = True

    def finish(self):
        self.target()


@pytest.fixture
def transcript():
    text = "Magandang araw, José & Niño."
    return {"schema_version": 1, "source": "Aral ni José.mp4", "language": "tl",
            "duration_ms": 2000, "created_at": "2026-10-20T12:00:00+08:00",
            "engine": "Synthetic UI test; no inference",
            "segments": [{"start_ms": 0, "end_ms": 2000, "text": text}], "text": text}


@pytest.fixture
def native_app(tmp_path, monkeypatch):
    # Withdraw inside Tk initialization, before App lays out or displays a window.
    original_init = tk.Tk.__init__

    def withdrawn_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.withdraw()

    monkeypatch.setattr(tk.Tk, "__init__", withdrawn_init)
    monkeypatch.setattr(app_module, "data_root", lambda: tmp_path / "app-data")
    DeferredThread.created = []
    monkeypatch.setattr(app_module.threading, "Thread", DeferredThread)
    messages = []
    monkeypatch.setattr(app_module.messagebox, "showerror", lambda *a, **k: messages.append(a))
    monkeypatch.setattr(app_module.messagebox, "showinfo", lambda *a, **k: messages.append(a))
    monkeypatch.setattr(app_module.messagebox, "askyesno", lambda *a, **k: False)
    window = app_module.App()
    # Poll deterministically; do not enter a mainloop or accumulate scheduled calls.
    for timer in window.tk.call("after", "info"):
        window.after_cancel(timer)
    monkeypatch.setattr(window, "after", lambda *a, **k: "test-timer")
    window.test_messages = messages
    yield window
    try:
        if window.winfo_exists():
            window.destroy()
    except tk.TclError:
        pass
    DeferredThread.created.clear()


def complete(window, transcript):
    window.events.put({"kind": "done", "transcript": transcript})
    window._poll()


def select_formats(window, *formats):
    for name, value in window.formats.items():
        value.set(name in formats)
    window._export_state()


def test_initial_and_completed_export_button_states(native_app, transcript):
    window = native_app
    assert window.export_button.instate(["disabled"])
    assert window.copy_button.instate(["disabled"])
    complete(window, transcript)
    assert window.export_button.instate(["!disabled"])
    assert window.copy_button.instate(["!disabled"])
    assert window.text.get("1.0", "end-1c") == transcript["text"]
    select_formats(window)
    assert window.export_button.instate(["disabled"])
    select_formats(window, "json")
    assert window.export_button.instate(["!disabled"])


def test_copy_uses_canonical_unicode_text(native_app, transcript, monkeypatch):
    window = native_app
    complete(window, transcript)
    clipboard = []
    monkeypatch.setattr(window, "clipboard_clear", clipboard.clear)
    monkeypatch.setattr(window, "clipboard_append", clipboard.append)
    window.copy()
    assert clipboard == [transcript["text"]]
    assert "copied" in window.status.get()


def test_select_new_file_clears_stale_transcript(native_app, transcript, tmp_path, monkeypatch):
    window = native_app
    complete(window, transcript)
    filename = tmp_path / "Bagong pelikula ñ.mp4"
    monkeypatch.setattr(app_module.filedialog, "askopenfilename", lambda **k: str(filename))
    window.choose_file()
    assert window.source.get() == str(filename)
    assert window.transcript is None
    assert window.export_button.instate(["disabled"])
    assert window.copy_button.instate(["disabled"])
    assert window.start_button.instate(["!disabled"])
    assert "Ready" in window.status.get()
    assert not DeferredThread.created


def test_multi_export_never_reruns_recognition(native_app, transcript, tmp_path, monkeypatch):
    window = native_app
    source = tmp_path / "Aral ni José.mp4"
    source.write_bytes(b"original media is never modified")
    window.source.set(str(source))
    complete(window, transcript)
    select_formats(window, "txt", "srt", "vtt", "json", "pdf")
    output = tmp_path / "exports"
    output.mkdir()
    monkeypatch.setattr(app_module.filedialog, "askdirectory", lambda **k: str(output))

    def forbid_recognition(*a, **k):
        raise AssertionError("Export must never instantiate the recognition engine")

    monkeypatch.setattr(app_module, "Transcriber", forbid_recognition)
    window.save()
    assert window.exporting
    assert window.export_button.instate(["disabled"])
    assert window.cancel_button.instate(["disabled"])
    assert window.start_button.instate(["disabled"])
    assert len(DeferredThread.created) == 1
    DeferredThread.created[0].finish()
    window._poll()
    assert not window.exporting
    assert window.export_button.instate(["!disabled"])
    assert "Saved 5" in window.status.get()
    assert source.read_bytes() == b"original media is never modified"
    exported = json.loads((output / "Aral ni José.json").read_text(encoding="utf-8"))
    assert exported["segments"] == transcript["segments"]
    assert (output / "Aral ni José.txt").read_text(encoding="utf-8").strip() == transcript["text"]
    assert {path.suffix for path in output.iterdir()} == {".pdf", ".srt", ".txt", ".vtt", ".json"}


def test_refusing_overwrite_leaves_original_files(native_app, transcript, tmp_path, monkeypatch):
    window = native_app
    window.source.set(str(tmp_path / "Aral ni José.mp4"))
    complete(window, transcript)
    select_formats(window, "txt", "json")
    existing = tmp_path / "Aral ni José.txt"
    existing.write_bytes(b"previous transcript")
    monkeypatch.setattr(app_module.filedialog, "askdirectory", lambda **k: str(tmp_path))
    window.save()
    assert not window.exporting
    assert not DeferredThread.created
    assert existing.read_bytes() == b"previous transcript"
    assert not (tmp_path / "Aral ni José.json").exists()


def test_file_appearing_during_overwrite_prompt_is_preserved(native_app, transcript, tmp_path, monkeypatch):
    window = native_app
    window.source.set(str(tmp_path / "Aral ni José.mp4"))
    complete(window, transcript)
    select_formats(window, "txt", "json")
    confirmed = tmp_path / "Aral ni José.txt"
    appeared = tmp_path / "Aral ni José.json"
    confirmed.write_bytes(b"previous transcript")
    monkeypatch.setattr(app_module.filedialog, "askdirectory", lambda **k: str(tmp_path))

    def confirm_only_listed_file(_title, prompt, **_kwargs):
        assert confirmed.name in prompt
        assert appeared.name not in prompt
        appeared.write_bytes(b"created by another program during confirmation")
        return True

    monkeypatch.setattr(app_module.messagebox, "askyesno", confirm_only_listed_file)
    window.save()
    assert window.exporting
    DeferredThread.created[0].finish()
    window._poll()
    assert not window.exporting
    assert "Couldn’t save" in window.status.get()
    assert confirmed.read_bytes() == b"previous transcript"
    assert appeared.read_bytes() == b"created by another program during confirmation"
    assert window.transcript == transcript
    assert window.export_button.instate(["!disabled"])
    assert "unconfirmed" in window.test_messages[0][1]


def test_cannot_overwrite_source_even_if_native_dialog_returns_source(native_app, transcript, tmp_path, monkeypatch):
    window = native_app
    source = tmp_path / "source.mp4"
    source.write_bytes(b"keep this source")
    window.source.set(str(source))
    complete(window, transcript)
    select_formats(window, "txt")
    monkeypatch.setattr(app_module.filedialog, "asksaveasfilename", lambda **k: str(source))
    window.save()
    assert source.read_bytes() == b"keep this source"
    assert not window.exporting
    assert not DeferredThread.created
    assert "source" in window.test_messages[0][1]


def test_cancel_native_save_dialog_does_no_work(native_app, transcript, monkeypatch):
    complete(native_app, transcript)
    select_formats(native_app, "txt")
    monkeypatch.setattr(app_module.filedialog, "asksaveasfilename", lambda **k: "")
    native_app.save()
    assert not native_app.exporting
    assert not DeferredThread.created


def test_transcription_cancellation_remains_retryable(native_app, tmp_path, monkeypatch):
    window = native_app

    class Cancellable:
        def __init__(self, *a, **k):
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

        def run(self, *a, **k):
            assert self.cancelled
            raise app_module.Cancelled("Synthetic cancellation")

    monkeypatch.setattr(app_module, "Transcriber", Cancellable)
    window.source.set(str(tmp_path / "test.wav"))
    window.start()
    assert window.busy
    assert window.browse.instate(["disabled"])
    assert window.cancel_button.instate(["!disabled"])
    window.cancel()
    assert window.cancel_button.instate(["disabled"])
    DeferredThread.created[0].finish()
    window._poll()
    assert not window.busy
    assert window.transcript is None
    assert window.progress["value"] == 0
    assert window.export_button.instate(["disabled"])
    assert window.start_button["text"] == "Retry"
    assert window.start_button.instate(["!disabled"])
    assert "Cancelled" in window.status.get()


def test_completion_queued_before_cancel_never_reports_complete(native_app, transcript, tmp_path, monkeypatch):
    window = native_app

    class JustFinished:
        def __init__(self, *a, **k):
            self.cancelled = False

        def run(self, *a, **k):
            return transcript

        def cancel(self):
            self.cancelled = True

    monkeypatch.setattr(app_module, "Transcriber", JustFinished)
    window.source.set(str(tmp_path / "test.wav"))
    window.start()
    DeferredThread.created[0].finish()  # Done is queued but the UI has not consumed it.
    window.cancel()
    window._poll()
    assert window.transcript is None
    assert window.export_button.instate(["disabled"])
    assert window.progress["value"] == 0
    assert "Cancelled" in window.status.get()


def test_error_event_cannot_enable_exports(native_app, tmp_path, monkeypatch):
    window = native_app

    class Failing:
        def __init__(self, *a, **k):
            pass

        def run(self, *a, **k):
            raise RuntimeError("Synthetic damaged media")

    monkeypatch.setattr(app_module, "Transcriber", Failing)
    window.source.set(str(tmp_path / "test.wav"))
    window.start()
    DeferredThread.created[0].finish()
    window._poll()
    assert not window.busy
    assert window.transcript is None
    assert window.export_button.instate(["disabled"])
    assert window.start_button["text"] == "Retry"
    assert "Synthetic damaged media" in window.text.get("1.0", "end")


def test_export_failure_preserves_preview_and_retry(native_app, transcript, tmp_path, monkeypatch):
    window = native_app
    window.source.set(str(tmp_path / "test.mp4"))
    complete(window, transcript)
    select_formats(window, "txt")
    monkeypatch.setattr(app_module.filedialog, "asksaveasfilename", lambda **k: str(tmp_path / "test.txt"))

    def fail_export(*a, **k):
        raise PermissionError("Synthetic locked destination")

    monkeypatch.setattr(app_module, "export_transcript", fail_export)
    window.save()
    DeferredThread.created[0].finish()
    window._poll()
    assert not window.exporting
    assert window.transcript == transcript
    assert window.text.get("1.0", "end-1c") == transcript["text"]
    assert window.export_button.instate(["!disabled"])
    assert "locked destination" in window.test_messages[0][1]


def test_invalid_formats_setting_does_not_prevent_launch(tmp_path, monkeypatch):
    # A valid JSON file can still have invalid field types after manual editing.
    settings = tmp_path / "app-data" / "settings.json"
    settings.parent.mkdir()
    settings.write_text('{"formats":null,"language":"English"}', encoding="utf-8")
    monkeypatch.setattr(app_module, "data_root", lambda: settings.parent)
    original_init = tk.Tk.__init__

    def withdrawn_init(self, *a, **k):
        original_init(self, *a, **k)
        self.withdraw()

    monkeypatch.setattr(tk.Tk, "__init__", withdrawn_init)
    window = None
    try:
        window = app_module.App()
        assert window.language.get() == "English"
        assert any(value.get() for value in window.formats.values())
    finally:
        if window is not None:
            window.destroy()


def test_processing_choice_and_profile_reach_worker(native_app, transcript, tmp_path, monkeypatch):
    window = native_app
    profile = app_module.load_profile(tmp_path)
    captured = {}

    class RecordingWorker:
        def __init__(self, runtime, model, **kwargs):
            captured.update(runtime=runtime, model=model, **kwargs)

        def run(self, _source, _language, emit):
            emit({"kind": "status", "message": "Transcribing on NVIDIA GPU…", "backend": "cuda", "model": profile.model.label})
            return transcript

    monkeypatch.setattr(app_module, "Transcriber", RecordingWorker)
    window.source.set(str(tmp_path / "sample.wav"))
    window.processing.set("CPU")
    window.start()
    assert captured["processing"] == "cpu"
    assert captured["threads"] == profile.cpu_threads
    assert captured["model_spec"] == profile.model
    assert window.processing_box.instate(["disabled"])
    DeferredThread.created[0].finish()
    window._poll()
    assert "NVIDIA GPU" in window.detail.get()
    assert window.processing_box.instate(["readonly"])


def test_profile_failure_remains_retryable(native_app, tmp_path, monkeypatch):
    window = native_app
    window.source.set(str(tmp_path / "sample.wav"))

    def damaged_profile(_path):
        raise ValueError("The local transcription profile is damaged.")

    monkeypatch.setattr(app_module, "load_profile", damaged_profile)
    window.start()
    window._poll()
    assert not window.busy
    assert window.start_button["text"] == "Retry"
    assert window.export_button.instate(["disabled"])
    assert "profile is damaged" in window.text.get("1.0", "end")


def test_gpu_fallback_explanation_survives_progress_and_completion(native_app, transcript):
    window = native_app
    window.job = object()
    window.busy = True
    window.events.put({"kind": "status", "backend": "cpu", "model": "Large-v3 Turbo", "fallback": True,
                       "message": "NVIDIA GPU initialization or memory failed. Retrying once on CPU…"})
    window.events.put({"kind": "progress", "backend": "cpu", "model": "Large-v3 Turbo", "percent": 50,
                       "message": "Transcribing on CPU…"})
    window._poll()
    assert "retried once on CPU" in window.detail.get()
    complete(window, transcript)
    assert "Large-v3 Turbo" in window.detail.get()
    assert "GPU unavailable; retried once on CPU" in window.detail.get()
