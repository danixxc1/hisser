# Hisser

A lightweight, portable Windows app for transcribing local audio and video with whisper.cpp. Select a file, choose its language, transcribe, preview or copy the text, then save **PDF, SRT, TXT, VTT or JSON**. Multiple exports reuse one canonical timed transcript.

Hisser runs locally after setup. It needs no cloud account, API key, daily quota or recording-length limit. The app transcribes the original language; it does not translate or generate papers.

## Features

- Native Tk/ttk window with file, Save As and export-folder dialogs.
- Auto language detection and 100 Whisper languages, including Tagalog and English.
- One job at a time, elapsed time, real progress, cancellation and retry.
- Selectable transcript preview, Copy text and multiple export formats.
- Unicode PDF text, pagination and timestamped subtitles.
- Source media preservation and explicit, race-safe overwrite confirmation.
- CPU only, two inference threads, one worker and below-normal child-process priority. No GPU toolkit or driver changes.

Common input containers include MP4, MKV, MOV, WebM, AVI, MP3, WAV, M4A, FLAC and OGG through FFmpeg. The media must have a decodable audio track. Input protocols are restricted to local files/pipes.

## Use the portable app

Open **Hisser.exe** inside the prepared portable folder, or use the desktop shortcut created by the packaging script. Keep the entire folder together:

```text
Hiss/
  Hisser.exe
  _internal/           # Python/Tk, app assets, FFmpeg and whisper.cpp
  data/
    models/            # One verified GGML model
    settings.json
    temp/              # Temporary audio, removed after each job
  USER_GUIDE.md
  portable.json
```

No installer, Windows app registration or Python activation is needed for daily use. The repository contains source, not a prebuilt app or model; build it using the steps below.

1. Select **Choose file…** and a local recording.
2. Leave **Auto-detect** or select **Tagalog / Filipino**, **English**, or another language.
3. Select **Transcribe**. Start with a short sample of your own recording.
4. Review the words, select text or use **Copy text**.
5. Choose formats and **Save transcript…**. One format uses Save As; several use a folder. Recognition is not repeated for exports.

See [the user guide](USER_GUIDE.md) for errors, storage and removal.

## Build from source

Requirements: Windows x64, Python **3.14** with tkinter, Git, and existing **FFmpeg + ffprobe on PATH**. The verified development machine used Python 3.14.7, Tk 9.0.4, PyInstaller 6.22.3 and [Gyan FFmpeg](https://www.gyan.dev/ffmpeg/builds/) 9.0.2. Preparation records and checks the selected FFmpeg build. Keep several GB of free disk space for downloads, build copies and staging. Working memory needs several GB beyond Windows and other apps.

```powershell
git clone https://github.com/danixxc1/hisser.git
cd hisser

# Use the full path to Python 3.14 if the py launcher is unavailable.
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt

# Download/verify the pinned CPU engine and ONE approved model.
# Existing FFmpeg/ffprobe and signed Microsoft runtime dependencies are reused.
.\.venv\Scripts\python.exe scripts\prepare_runtime.py

# Build the windowed, folder-based EXE.
.\scripts\build.ps1

# Prepare a portable folder and branded desktop shortcut.
# Default destination: your Documents\Tools\Hiss.
.\scripts\package-portable.ps1
```

Choose another folder with `-Destination 'D:\Tools\Hiss'`. `-WhatIf` previews deployment without changes. Packaging moves the single prepared model/data directory into the portable folder, checks the EXE, exports and relative data paths, and restores the previous copy on failure when possible. It rejects unrecognized destination folders and linked paths. Personal transcripts should be saved outside the app folder.

For repeat builds, preserve the portable `data` directory. Use `prepare_runtime.py --skip-model` or restore the verified `_internal\runtime` files from the portable app to avoid another model copy. Read [maintenance instructions](scripts/MAINTENANCE.md) before an update. `install.ps1` is a compatibility wrapper for portable packaging; it does not register an app.

## Model and storage

The multilingual `ggml-large-v3-q5_0.bin` model is approximately **1.08 GB**. It is a whisper.cpp GGML model; faster-whisper models are a different format. Setup verifies the [pinned upstream model](https://huggingface.co/ggerganov/whisper.cpp/tree/5359861c739e955e79d9a303bcbc70fb988958b1) against LFS size and SHA-256. See [runtime inputs](runtime/README.md) for pinned engine/model hashes.

The tested portable folder occupies approximately **1.60 GB**, including the runtime and one model. Decoding needs additional temporary working space, about **115 MB per hour** of recording; exact digital-silence trimming may briefly need another audio copy. Temporary job files are cleaned after success, cancellation and failure. The model is not loaded on startup.

Close Hisser, delete the portable folder, then delete its desktop shortcut to remove all Hisser-managed app/model/settings/temp files. The source project and transcripts saved elsewhere stay intact. Windows manages its own shared history and security records.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest-work
```

The automated tests do not download a model. Windows CI runs the same suite. [Testing details](docs/TESTING.md) explain synthetic fixtures and optional actual-model checks. Local reports, media, models, binaries, credentials and settings are excluded from Git.

Measured on one Windows 11 laptop with 16 GB RAM:

| Controlled synthetic test | Observed result |
| --- | --- |
| 14.032 seconds of clear English, language fixed to English | 72.985 seconds; known phrase recognized |
| Same sample with auto detection | 108.415 seconds; detected English; source hash unchanged |
| Recognition process memory | About 2.1 GB peak RSS |
| 30:38.523 source, exact silence then speech at 30:30 | Late phrase recognized with timestamps after minute 30 |

The long fixture verifies complete source scanning and timestamp restoration. The engine trims only long, exact-zero outer silence with context; nonzero quiet samples and interior gaps remain. This is not a continuous 30-minute speech performance benchmark. Film and Tagalog accuracy are not established; names, mixed languages, music and overlapping dialogue need review.

Runtime scans completed without detected threats. The model matched its upstream SHA-256; a separate local Defender model scan returned `0x80508023`, so that scan was unconfirmed. No security settings were changed. Packaged executables are not code-signed.

## Project layout and licenses

`hisser/` contains the UI, engine and exporters. `tests/` holds behavior tests; `scripts/` prepares, builds and updates the portable app. Runtime/model weights and large QA files are generated locally.

See [third-party notices](THIRD_PARTY_NOTICES.md) and bundled notices for dependencies. No project-wide open-source license has been selected for Hisser's own source; the repository is maintained privately.
