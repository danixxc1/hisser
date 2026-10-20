"""Native task-focused interface. Workers never call Tk."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .engine import Cancelled, Transcriber
from .exports import export_transcript

LANGUAGES = {
    "Auto-detect": "auto", "Tagalog / Filipino": "tl", "English": "en",
    "Afrikaans": "af", "Albanian": "sq", "Amharic": "am", "Arabic": "ar",
    "Armenian": "hy", "Assamese": "as", "Azerbaijani": "az", "Bashkir": "ba",
    "Basque": "eu", "Belarusian": "be", "Bengali": "bn", "Bosnian": "bs",
    "Breton": "br", "Bulgarian": "bg", "Burmese": "my", "Cantonese": "yue",
    "Catalan": "ca", "Chinese": "zh", "Croatian": "hr", "Czech": "cs",
    "Danish": "da", "Dutch": "nl", "Estonian": "et", "Faroese": "fo",
    "Finnish": "fi", "French": "fr", "Galician": "gl", "Georgian": "ka",
    "German": "de", "Greek": "el", "Gujarati": "gu", "Haitian Creole": "ht",
    "Hausa": "ha", "Hawaiian": "haw", "Hebrew": "he", "Hindi": "hi",
    "Hungarian": "hu", "Icelandic": "is", "Indonesian": "id", "Italian": "it",
    "Japanese": "ja", "Javanese": "jw", "Kannada": "kn", "Kazakh": "kk",
    "Khmer": "km", "Korean": "ko", "Lao": "lo", "Latin": "la", "Latvian": "lv",
    "Lingala": "ln", "Lithuanian": "lt", "Luxembourgish": "lb",
    "Macedonian": "mk", "Malagasy": "mg", "Malay": "ms", "Malayalam": "ml",
    "Maltese": "mt", "Maori": "mi", "Marathi": "mr", "Mongolian": "mn",
    "Nepali": "ne", "Norwegian": "no", "Nynorsk": "nn", "Occitan": "oc",
    "Pashto": "ps", "Persian": "fa", "Polish": "pl", "Portuguese": "pt",
    "Punjabi": "pa", "Romanian": "ro", "Russian": "ru", "Sanskrit": "sa",
    "Serbian": "sr", "Shona": "sn", "Sindhi": "sd", "Sinhala": "si",
    "Slovak": "sk", "Slovenian": "sl", "Somali": "so", "Spanish": "es",
    "Sundanese": "su", "Swahili": "sw", "Swedish": "sv", "Tajik": "tg",
    "Tamil": "ta", "Tatar": "tt", "Telugu": "te", "Thai": "th", "Tibetan": "bo",
    "Turkish": "tr", "Turkmen": "tk", "Ukrainian": "uk", "Urdu": "ur",
    "Uzbek": "uz", "Vietnamese": "vi", "Welsh": "cy", "Yiddish": "yi",
    "Yoruba": "yo",
}


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def data_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "data"
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Hisser"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Hisser")
        self.geometry("1000x800")
        self.minsize(760, 680)
        self.configure(bg="#edf2ee")
        self.events = queue.Queue()
        self.transcript = None
        self.job = None
        self.worker = None
        self.busy = False
        self.exporting = False
        self.closing = False
        self.cancel_requested = False
        self.started = 0.0
        self.settings_path = data_root() / "settings.json"
        try:
            self.settings = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.settings = {}
        if not isinstance(self.settings, dict):
            self.settings = {}
        saved_formats = self.settings.get("formats", ["txt", "pdf"])
        if not isinstance(saved_formats, list) or not all(isinstance(f, str) and f in ("pdf", "srt", "txt", "vtt", "json") for f in saved_formats):
            saved_formats = ["txt", "pdf"]
        self.settings["formats"] = saved_formats
        if not isinstance(self.settings.get("language", "Auto-detect"), str):
            self.settings["language"] = "Auto-detect"
        for directory in ("input_dir", "export_dir"):
            if not isinstance(self.settings.get(directory), str) or not Path(self.settings[directory]).is_dir():
                self.settings.pop(directory, None)
        self.source = tk.StringVar()
        self.language = tk.StringVar(value=self.settings.get("language", "Auto-detect"))
        if self.language.get() not in LANGUAGES:
            self.language.set("Auto-detect")
        self.status = tk.StringVar(value="Choose an audio or video file to begin.")
        self.elapsed = tk.StringVar(value="")
        self.detail = tk.StringVar(value="Your transcript will appear here.")
        self.formats = {f: tk.BooleanVar(value=f in self.settings.get("formats", ["txt", "pdf"])) for f in ("pdf", "srt", "txt", "vtt", "json")}
        self._style()
        self._build()
        try:
            self.iconbitmap(str(resource_root() / "assets/hisser.ico"))
        except tk.TclError:
            pass
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Control-o>", lambda e: self.choose_file() if not self.busy else None)
        self.after(100, self._poll)

    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", font=("Segoe UI", 11), background="#edf2ee", foreground="#192d23")
        s.configure("TFrame", background="#edf2ee")
        s.configure("TLabel", background="#edf2ee", foreground="#192d23")
        s.configure("Title.TLabel", font=("Segoe UI", 25, "bold"))
        s.configure("Heading.TLabel", font=("Segoe UI", 13, "bold"))
        s.configure("Muted.TLabel", foreground="#4e6256", font=("Segoe UI", 10))
        s.configure("Status.TLabel", font=("Segoe UI", 11, "bold"))
        s.configure("TButton", padding=(14, 8), background="#ffffff", foreground="#192d23", borderwidth=1, focusthickness=2, focuscolor="#285a45")
        s.map("TButton", background=[("disabled", "#e6ebe7"), ("pressed", "#d8e2db"), ("active", "#f7faf7")], foreground=[("disabled", "#68776c")])
        s.configure("Primary.TButton", background="#285a45", foreground="white", font=("Segoe UI", 11, "bold"))
        s.map("Primary.TButton", background=[("disabled", "#d7e0da"), ("pressed", "#163d2b"), ("active", "#326b52")], foreground=[("disabled", "#5f7064"), ("!disabled", "white")])
        s.configure("TCombobox", padding=7, fieldbackground="white", foreground="#192d23", arrowsize=16)
        s.map("TCombobox", fieldbackground=[("readonly", "white")])
        s.configure("TEntry", padding=8, fieldbackground="white")
        s.map("TEntry", fieldbackground=[("readonly", "white")], foreground=[("readonly", "#192d23")])
        s.configure("TCheckbutton", padding=(0, 4), focuscolor="#285a45")
        s.configure("Horizontal.TProgressbar", background="#285a45", troughcolor="#dce5de", borderwidth=0, thickness=5)

    def _build(self):
        body = ttk.Frame(self, padding=(30, 22, 30, 18))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(6, weight=1)
        header = ttk.Frame(body)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 22))
        try:
            self.logo = tk.PhotoImage(file=str(resource_root() / "assets/hisser-64.png"))
            ttk.Label(header, image=self.logo).pack(side="left", padx=(0, 13))
        except tk.TclError:
            pass
        names = ttk.Frame(header)
        names.pack(side="left")
        ttk.Label(names, text="Hisser", style="Title.TLabel").pack(anchor="w")
        ttk.Label(names, text="Local audio & video transcription", style="Muted.TLabel").pack(anchor="w")
        ttk.Button(header, text="Help", command=self.help).pack(side="right")
        ttk.Label(body, text="Audio or video", style="Heading.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 7))
        file_row = ttk.Frame(body)
        file_row.grid(row=2, column=0, sticky="ew")
        file_row.columnconfigure(0, weight=1)
        self.file_entry = ttk.Entry(file_row, textvariable=self.source, state="readonly", takefocus=True)
        self.file_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.browse = ttk.Button(file_row, text="Choose file…", command=self.choose_file)
        self.browse.grid(row=0, column=1)
        controls = ttk.Frame(body)
        controls.grid(row=3, column=0, sticky="ew", pady=(15, 17))
        ttk.Label(controls, text="Language").pack(side="left", padx=(0, 10))
        self.language_box = ttk.Combobox(controls, textvariable=self.language, values=list(LANGUAGES), state="readonly", width=23)
        self.language_box.pack(side="left")
        self.start_button = ttk.Button(controls, text="Transcribe", style="Primary.TButton", command=self.start, state="disabled")
        self.start_button.pack(side="right")
        self.cancel_button = ttk.Button(controls, text="Cancel", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="right", padx=10)
        state = ttk.Frame(body)
        state.grid(row=4, column=0, sticky="ew", pady=(0, 16))
        state.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(state, textvariable=self.status, style="Status.TLabel", wraplength=800)
        self.status_label.grid(row=0, column=0, sticky="w")
        ttk.Label(state, textvariable=self.elapsed, style="Muted.TLabel").grid(row=0, column=1, sticky="e", padx=(10, 0))
        self.progress = ttk.Progressbar(state, maximum=100, mode="determinate")
        self.progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(9, 0))
        preview_head = ttk.Frame(body)
        preview_head.grid(row=5, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(preview_head, text="Transcript", style="Heading.TLabel").pack(side="left")
        self.copy_button = ttk.Button(preview_head, text="Copy text", command=self.copy, state="disabled")
        self.copy_button.pack(side="right")
        preview = ttk.Frame(body)
        preview.grid(row=6, column=0, sticky="nsew")
        preview.rowconfigure(0, weight=1)
        preview.columnconfigure(0, weight=1)
        self.text = tk.Text(preview, wrap="word", font=("Segoe UI", 12), padx=18, pady=16, bg="#ffffff", fg="#1c2e24", selectbackground="#c4dfce", selectforeground="#122a1b", insertbackground="#285a45", relief="solid", bd=1, highlightthickness=1, highlightbackground="#cbd6ce", highlightcolor="#285a45", spacing3=8, state="disabled", height=8, takefocus=True)
        self.text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(preview, orient="vertical", command=self.text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.text.configure(yscrollcommand=scroll.set)
        self.text.bind("<Control-a>", self._select_all)
        self.text.bind("<Tab>", lambda e: (self.text.tk_focusNext().focus_set(), "break")[1])
        self.text.bind("<Shift-Tab>", lambda e: (self.text.tk_focusPrev().focus_set(), "break")[1])
        self._preview("Choose a file above, then select Transcribe.\n\nWhen it’s ready, select words here or use Copy text. Choose one or more formats below to save the same transcript.")
        ttk.Label(body, textvariable=self.detail, style="Muted.TLabel").grid(row=7, column=0, sticky="w", pady=(7, 14))
        exports = ttk.Frame(body)
        exports.grid(row=8, column=0, sticky="ew")
        ttk.Label(exports, text="Save as", style="Heading.TLabel").pack(side="left", padx=(0, 16))
        self.format_checks = []
        for fmt, var in self.formats.items():
            check = ttk.Checkbutton(exports, text=fmt.upper(), variable=var, command=self._export_state)
            check.pack(side="left", padx=(0, 13))
            self.format_checks.append(check)
        self.export_button = ttk.Button(exports, text="Save transcript…", style="Primary.TButton", command=self.save, state="disabled")
        self.export_button.pack(side="right")
        ttk.Label(body, text="Local processing · Original language · No time limit", style="Muted.TLabel").grid(row=9, column=0, sticky="w", pady=(15, 0))
        self.bind("<Configure>", self._resize)

    def _resize(self, event):
        if event.widget is self:
            self.status_label.configure(wraplength=max(420, event.width - 200))

    def _select_all(self, _event):
        self.text.tag_add("sel", "1.0", "end-1c")
        return "break"

    def _preview(self, value):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", value)
        self.text.configure(state="disabled")

    def choose_file(self):
        if self.busy or self.exporting:
            return
        filename = filedialog.askopenfilename(parent=self, title="Choose audio or video", initialdir=self.settings.get("input_dir"), filetypes=[("Audio and video", "*.mp4 *.mkv *.mov *.webm *.avi *.mp3 *.wav *.m4a *.flac *.ogg"), ("All files", "*.*")])
        if filename:
            self.source.set(filename)
            self.settings["input_dir"] = str(Path(filename).parent)
            self.transcript = None
            self.copy_button.configure(state="disabled")
            self._export_state()
            self.start_button.configure(state="normal", text="Transcribe")
            self.status.set("Ready to transcribe.")
            self.elapsed.set("")
            self.progress.configure(value=0)
            self.detail.set("Original-language transcription. The source file stays unchanged.")
            self._preview("Your transcript will appear here after transcription.")

    def start(self):
        if self.busy or self.exporting or not self.source.get():
            return
        self.busy = True
        self.cancel_requested = False
        self.started = time.monotonic()
        self.transcript = None
        self._set_busy(True)
        self._preview("Transcribing locally. You can leave this window open while you work.")
        self.detail.set("Large-v3 model · CPU · This can take longer than the recording.")
        self.status.set("Preparing audio…")
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(15)
        self.job = Transcriber(resource_root() / "runtime", data_root() / "models/ggml-large-v3-q5_0.bin", temp_root=data_root() / "temp")
        source, language = Path(self.source.get()), LANGUAGES[self.language.get()]
        def work():
            try:
                result = self.job.run(source, language, self.events.put)
                self.events.put({"kind": "done", "transcript": result})
            except Cancelled:
                self.events.put({"kind": "cancelled"})
            except Exception as exc:
                self.events.put({"kind": "error", "message": str(exc) or type(exc).__name__})
        self.worker = threading.Thread(target=work, name="Hisser transcription", daemon=True)
        self.worker.start()

    def _set_busy(self, value):
        for w in (self.browse, self.start_button):
            w.configure(state="disabled" if value else "normal")
        self.language_box.configure(state="disabled" if value else "readonly")
        self.cancel_button.configure(state="normal" if value else "disabled")
        self.copy_button.configure(state="normal" if self.transcript and not value else "disabled")
        self._export_state()

    def cancel(self):
        if self.busy and self.job:
            self.cancel_requested = True
            self.cancel_button.configure(state="disabled")
            self.status.set("Cancelling and cleaning up…")
            self.job.cancel()

    def _poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event.get("kind")
                if kind in ("status", "progress"):
                    if self.job and not self.cancel_requested and not self.closing:
                        self.status.set(event.get("message", "Transcribing…"))
                        percent = event.get("percent")
                        if percent is not None:
                            self.progress.stop()
                            self.progress.configure(mode="determinate", value=min(99, max(0, percent)))
                elif kind in ("done", "error", "cancelled"):
                    if self.cancel_requested:
                        kind = "cancelled"
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=100 if kind == "done" else 0)
                    self.busy = False
                    if kind == "done":
                        self.transcript = event["transcript"]
                        words = len(self.transcript.get("text", "").split())
                        self.status.set("Transcription complete. Choose your export formats below.")
                        self.detail.set(f"{words:,} words · Language: {self.transcript.get('language', 'unknown')} · {len(self.transcript['segments']):,} timed segments")
                        self._preview(self.transcript.get("text", "") or "No speech was detected in this file.")
                    elif kind == "cancelled":
                        self.status.set("Cancelled. You can try again or choose another file.")
                        self.detail.set("Temporary audio removed. No transcript was saved.")
                        self._preview("Transcription cancelled.")
                    else:
                        self.status.set("Couldn’t transcribe this file. See the details below.")
                        self.detail.set("Choose another file or select Retry.")
                        self._preview(event["message"])
                    self.start_button.configure(text="Transcribe again" if kind == "done" else "Retry")
                    self._set_busy(False)
                elif kind == "exported":
                    self.exporting = False
                    self.status.set(f"Saved {len(event['paths'])} file(s) to {Path(event['paths'][0]).parent}")
                    self._set_busy(False)
                elif kind == "export_error":
                    self.exporting = False
                    self.status.set("Couldn’t save the transcript. Choose another location and retry.")
                    self._set_busy(False)
                    messagebox.showerror("Export failed", event["message"], parent=self)
        except queue.Empty:
            pass
        if self.busy:
            seconds = int(time.monotonic() - self.started)
            self.elapsed.set(f"Elapsed {seconds // 60:02}:{seconds % 60:02}")
        if self.closing and not self.busy and not self.exporting:
            self._finish_close()
            return
        self.after(100, self._poll)

    def copy(self):
        if self.transcript:
            self.clipboard_clear()
            self.clipboard_append(self.transcript.get("text", ""))
            self.status.set("Transcript copied.")

    def _export_state(self):
        if hasattr(self, "export_button"):
            self.export_button.configure(state="normal" if self.transcript is not None and any(v.get() for v in self.formats.values()) and not self.busy and not self.exporting else "disabled")

    def save(self):
        if self.transcript is None or self.busy or self.exporting:
            return
        formats = [f for f, v in self.formats.items() if v.get()]
        if not formats:
            return
        stem = Path(self.source.get()).stem
        if len(formats) == 1:
            fmt = formats[0]
            selected = filedialog.asksaveasfilename(parent=self, title="Save transcript", initialdir=self.settings.get("export_dir"), initialfile=stem + "." + fmt, defaultextension="." + fmt, filetypes=[(fmt.upper(), "*." + fmt)], confirmoverwrite=False)
            if not selected:
                return
            destinations = {fmt: Path(selected)}
        else:
            selected = filedialog.askdirectory(parent=self, title="Choose a folder for transcript files", initialdir=self.settings.get("export_dir"), mustexist=True)
            if not selected:
                return
            destinations = {fmt: Path(selected) / (stem + "." + fmt) for fmt in formats}
        source_resolved = Path(self.source.get()).resolve()
        if any(p.resolve() == source_resolved for p in destinations.values()):
            messagebox.showerror("Choose another name", "An export cannot replace the source media file.", parent=self)
            return
        approved_overwrites = {p.resolve() for p in destinations.values() if p.exists()}
        if approved_overwrites and not messagebox.askyesno("Replace existing files?", "Replace these transcript files?\n\n" + "\n".join(p.name for p in sorted(approved_overwrites)), parent=self, default="no"):
            return
        overwrite = bool(approved_overwrites)
        self.settings["export_dir"] = str(next(iter(destinations.values())).parent)
        self.exporting = True
        self._set_busy(True)
        self.cancel_button.configure(state="disabled")
        self.status.set("Saving transcript files…")
        transcript = self.transcript
        def write():
            try:
                result = export_transcript(transcript, destinations, overwrite=overwrite, approved_overwrites=approved_overwrites)
                self.events.put({"kind": "exported", "paths": result})
            except Exception as exc:
                self.events.put({"kind": "export_error", "message": str(exc)})
        threading.Thread(target=write, name="Hisser export", daemon=True).start()

    def help(self):
        messagebox.showinfo("Using Hisser", "1. Choose a local audio or video file.\n2. Use Auto-detect, or choose Tagalog / Filipino or another language.\n3. Select Transcribe. Cancel stops this job safely.\n4. Copy text, or select formats and Save transcript.\n\nMultiple formats use a folder; one format opens Save As. Exports never rerun recognition.\n\nProcessing stays on this computer after setup. The large model can be slow on CPU; start with a short sample. Temporary decoded audio uses about 115 MB per hour and is removed after each job. Model/runtime working memory needs several GB.\n\nSpeech recognition can make mistakes, especially names, background dialogue and mixed languages. Review important wording against the recording.\n\nHisser 1.0.0", parent=self)

    def close(self):
        if self.exporting:
            self.status.set("Finishing the export before closing…")
            self.closing = True
            return
        if self.busy:
            if not messagebox.askyesno("Cancel and close?", "Cancel transcription and close Hisser?", parent=self, default="no"):
                return
            self.closing = True
            self.cancel()
            return
        self._finish_close()

    def _finish_close(self):
        self.settings.update(language=self.language.get(), formats=[f for f, v in self.formats.items() if v.get()])
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.settings_path.with_suffix(".tmp")
            temp.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.settings_path)
        except OSError:
            pass
        self.destroy()
