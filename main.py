"""Portable windowed entry point and a hidden package verification mode."""
import ctypes
import json
import os
from pathlib import Path
import sys

if os.name == "nt":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Hisser.LocalTranscriber.1")
    except OSError:
        pass

from hisser.app import App, resource_root, data_root


def main():
    if "--self-test" in sys.argv:
        import tkinter as tk
        from hisser.exports import export_transcript
        from hisser.models import load_profile
        root = tk.Tk()
        root.withdraw()
        profile = load_profile(data_root())
        model_path = data_root() / "models" / profile.model.filename
        try:
            metadata = json.loads(model_path.with_suffix(".bin.metadata.json").read_text(encoding="utf-8-sig"))
            model_verified = (model_path.is_file() and model_path.stat().st_size == profile.model.size
                              and metadata.get("size") == profile.model.size
                              and metadata.get("sha256") == profile.model.sha256)
        except (OSError, ValueError, AttributeError):
            model_verified = False
        cpu_files = ("whisper-cli.exe", "whisper.dll", "ggml.dll", "ggml-base.dll", "ggml-cpu-x64.dll",
                     "ffmpeg.exe", "ffprobe.exe", "msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll", "vcomp140.dll")
        cuda_files = ("whisper-cli.exe", "whisper.dll", "ggml.dll", "ggml-base.dll", "ggml-cpu-x64.dll", "ggml-cuda.dll",
                      "cudart64_110.dll", "nvrtc64_112_0.dll", "nvrtc-builtins64_118.dll",
                      "cublas64_11.dll", "cublasLt64_11.dll", "msvcp140.dll", "vcruntime140.dll",
                      "vcruntime140_1.dll", "vcomp140.dll")
        result = {
            "tk": root.tk.call("info", "patchlevel"), "resource_root": str(resource_root()),
            "data_root": str(data_root()), "portable": bool(getattr(sys, "frozen", False)),
            "runtime_files": all((resource_root() / "runtime" / f).is_file()
                                 and (resource_root() / "runtime" / f).stat().st_size > 0 for f in cpu_files),
            "model": model_verified, "model_id": profile.model.id, "cpu_threads": profile.cpu_threads,
            "cuda_runtime": all((resource_root() / "runtime" / "cuda" / f).is_file()
                                and (resource_root() / "runtime" / "cuda" / f).stat().st_size > 0 for f in cuda_files),
        }
        root.destroy()
        from tempfile import TemporaryDirectory
        fixture = {"schema_version": 1, "source": "Package check - José & Niño.wav", "language": "tl", "duration_ms": 2000, "created_at": "2026-10-20T00:00:00Z", "engine": "Synthetic package check", "segments": [{"start_ms": 0, "end_ms": 2000, "text": "Magandang araw, José & Niño."}], "text": "Magandang araw, José & Niño."}
        data_root().mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="package-check-", dir=data_root()) as work:
            destinations = {fmt: Path(work) / ("check." + fmt) for fmt in ("pdf", "srt", "txt", "vtt", "json")}
            files = export_transcript(fixture, destinations)
            result["exports"] = len(files) == 5 and all(p.stat().st_size > 0 for p in files)
        output = Path(sys.argv[sys.argv.index("--self-test") + 1])
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return
    mutex = None
    if os.name == "nt":
        ctypes.windll.kernel32.CreateMutexW.restype = ctypes.c_void_p
        mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\Hisser.LocalTranscriber.1")
        if ctypes.windll.kernel32.GetLastError() == 183:
            from tkinter import messagebox
            messagebox.showinfo("Hisser", "Hisser is already open. Switch to its window in the taskbar.")
            return
    try:
        App().mainloop()
    except Exception as exc:
        from tkinter import messagebox
        messagebox.showerror("Hisser could not start", "Hisser needs its complete folder and permission to write to its data folder.\n\n" + str(exc)[:800])
    finally:
        if mutex:
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(mutex))


if __name__ == "__main__":
    main()
