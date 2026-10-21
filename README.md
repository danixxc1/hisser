# Hisser

A portable Windows app for transcribing local audio and video with whisper.cpp. Select a file, choose its language, transcribe, preview or copy the text, then save **PDF, SRT, TXT, VTT or JSON**. Multiple exports reuse one canonical timed transcript.

Hisser runs locally after setup. It needs no cloud account, API key, daily quota or recording-length limit. The app transcribes the original language; it does not translate or generate papers.

## Download and run

**[Download the latest portable app from Releases](https://github.com/danixxc1/hisser/releases/latest).** Open the release's **Assets** section and download **Hisser-1.1.0-windows-x64.zip** and its **Hisser-1.1.0-windows-x64.zip.sha256** file. If a newer version is listed, choose that version's Windows x64 ZIP and matching checksum.

1. Right-click the downloaded ZIP and choose **Extract All…**. Choose a writable location, such as your Documents folder.
2. Open the extracted **Hisser** folder and double-click **Hisser.exe**.
3. Keep **Hisser.exe**, **_internal** and **data** together. Run the extracted copy, rather than opening the EXE inside the ZIP.

The release includes the app, recognition model and required libraries. You do **not** need Python, Git, FFmpeg, an API key, an installer or administrator access for normal use. **Code → Download ZIP** downloads the developer source and will not give you the ready-to-run app.

Use **Windows 10 or 11, 64-bit x64**. Windows 11 with 16 GB RAM and an RTX 3050 Laptop GPU was tested; 16 GB RAM is recommended. Allow **8 GB free disk space** for the download, extracted app and working space. The extracted public release is approximately **2.45 GB**, with extra temporary space needed while processing recordings. ARM64 and 32-bit Windows are not tested.

Leave **Processing** on **Automatic** to use an available compatible NVIDIA GPU and its existing driver. CPU processing is available when acceleration cannot be used. A GPU toolkit or new driver is not installed; CPU transcription can take longer than the recording.

The EXE is **not code-signed**, so Windows may show a warning. Check that the download came from this repository's release and compare its SHA-256 with the release checksum before deciding whether to run it. Do not disable Windows security protections. See [the user guide](USER_GUIDE.md#download-verification) for the check.

## Features

- Native Tk/ttk window with file, Save As and export-folder dialogs.
- Auto language detection and 100 Whisper languages, including Tagalog and English.
- One job at a time, elapsed time, real progress, cancellation and retry.
- Selectable transcript preview, Copy text and multiple export formats.
- Unicode PDF text, pagination and timestamped subtitles.
- Source media preservation and explicit, race-safe overwrite confirmation.
- **Automatic / CPU** processing. Automatic tries the bundled NVIDIA CUDA runtime; CPU forces the CPU engine. GPU initialization or memory failure retries once on CPU, unless cancelled.
- One recognition worker, profile-selected CPU threads and below-normal child-process priority. No GPU toolkit or driver changes.

Common input containers include MP4, MKV, MOV, WebM, AVI, MP3, WAV, M4A, FLAC and OGG through FFmpeg. The media must have a decodable audio track. Input protocols are restricted to local files/pipes.

## Use the portable app

Open **Hisser.exe** inside the extracted portable folder. You can create your own desktop shortcut to it. Keep the entire folder together:

```text
Hisser/
  Hisser.exe
  _internal/           # Python/Tk, app assets, FFmpeg and whisper.cpp
  data/
    models/            # One verified GGML model
    transcription-profile.json  # Selected model ID and CPU thread count
    settings.json
    temp/              # Temporary audio, removed after each job
  USER_GUIDE.md
  portable.json
```

No installer, Windows app registration or Python activation is needed for daily use. Ready-to-run packages are attached to [GitHub Releases](https://github.com/danixxc1/hisser/releases); the repository's source tree does not contain executable binaries or models.

1. Select **Choose file…** and a local recording.
2. Leave **Auto-detect** or select **Tagalog / Filipino**, **English**, or another language.
3. Leave **Processing** on **Automatic**, or choose **CPU**. Select **Transcribe**, starting with a short sample of your own recording.
4. Review the words, select text or use **Copy text**.
5. Choose formats and **Save transcript…**. One format uses Save As; several use a folder. Recognition is not repeated for exports.

See [the user guide](USER_GUIDE.md) for errors, updates, storage and removal.

## Build from source

Requirements: Windows x64, Python **3.14** with tkinter, Git, and existing **FFmpeg + ffprobe on PATH**. The development machine used Python 3.14.7, Tk 9.0.4, PyInstaller 6.22.3 and [Gyan FFmpeg](https://www.gyan.dev/ffmpeg/builds/) 9.0.2. CUDA acceleration also needs a compatible NVIDIA GPU and its existing driver. Preparation bundles verified CUDA 11.8/cuBLAS libraries locally; it installs no toolkit or driver. Keep several GB of free disk space for downloads, build copies and staging. Recognition needs several GB of working memory beyond Windows and other apps.

```powershell
git clone https://github.com/danixxc1/hisser.git
cd hisser

# Use the full path to Python 3.14 if the py launcher is unavailable.
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt

# Download/verify CPU + CUDA engines and ONE approved model.
# Existing FFmpeg/ffprobe and signed Microsoft runtime dependencies are reused.
.\.venv\Scripts\python.exe scripts\prepare_runtime.py --backend cuda

# Build the windowed, folder-based EXE.
.\scripts\build.ps1 -Backend cuda

# Prepare a portable folder and branded desktop shortcut.
# Default destination: your Documents\Tools\Hiss.
.\scripts\package-portable.ps1
```

Choose another folder with `-Destination 'D:\Tools\Hiss'`. `-WhatIf` previews deployment without changes. Packaging moves the single prepared model/data directory into the portable folder, checks the EXE, exports and relative data paths, and restores the previous copy on failure when possible. It rejects unrecognized destination folders and linked paths. Personal transcripts should be saved outside the app folder.

For a CPU-only package, prepare with `--backend cpu` and build with `-Backend cpu`; CUDA DLLs are excluded. For repeat CUDA builds, preserve portable `data` and use `prepare_runtime.py --backend cuda --skip-model`, or restore the complete verified `_internal\runtime` from the portable app to avoid another model copy. Read [maintenance instructions](scripts/MAINTENANCE.md) before an update. `install.ps1` is a compatibility wrapper for portable packaging; it does not register an app.

Public releases use a separately reviewed redistribution runtime, including a native-only LGPL FFmpeg build and Microsoft DLLs from Visual Studio's redistribution directory. Do not publish an arbitrary FFmpeg build from PATH or DLLs copied from a Windows system folder. See [distribution requirements](docs/DISTRIBUTION.md) and [the release checklist](docs/RELEASING.md).

## Model and storage

The selected model is recorded in `data/transcription-profile.json`; it is not chosen by renaming files. The default remains multilingual **large-v3 Q5** (approximately **1.08 GB**). **Large-v3 Turbo Q5** (approximately **574 MB**) is an optional comparison profile, prepared with `--model large-v3-turbo-q5_0`. Keep comparison models in a separate local folder and retain the current large model until a person approves Turbo's wording against the audio. The app never downloads or upgrades a model automatically.

Both are whisper.cpp GGML models; faster-whisper models are a different format. Setup verifies the [pinned upstream revision](https://huggingface.co/ggerganov/whisper.cpp/tree/5359861c739e955e79d9a303bcbc70fb988958b1) against LFS size and SHA-256. See [runtime inputs](runtime/README.md) for engine/model hashes.

Packaging requires **exactly one model** and a complete portable folder **strictly below 4 GB** (4,000,000,000 bytes), including its runtime and data. Development downloads, build copies and staging need additional space. Decoding needs about **115 MB per hour** of recording in temporary working space; exact digital-silence trimming may briefly need another audio copy. Temporary job files are cleaned after success, cancellation and failure. The model is not loaded on startup. See [measured performance and footprint](docs/PERFORMANCE.md) for tested configurations.

Close Hisser, delete the portable folder, then delete its desktop shortcut to remove all Hisser-managed app/model/settings/temp files. The source project and transcripts saved elsewhere stay intact. Windows manages its own shared history and security records.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest-work
```

The automated tests do not download a model. Windows CI runs the same suite. [Testing details](docs/TESTING.md) explain synthetic fixtures and optional actual-model checks. Local reports, media, models, binaries, credentials and settings are excluded from Git.

See [performance results](docs/PERFORMANCE.md) for measured CPU thread comparisons, GPU runs, memory and limitations. Performance depends on the model, hardware, language and recording. Synthetic checks do not establish film or Tagalog accuracy; names, missing dialogue and meaning-changing mistakes require review against the audio. Turbo is not promoted automatically.

The long fixture verifies complete source scanning and timestamp restoration after minute 30. The engine trims only long, exact-zero outer silence with context; nonzero quiet samples and interior gaps remain. This is not a continuous 30-minute speech performance benchmark.

Preparation checks pinned upstream hashes and requests Windows Security scans; local verification reports record the result. No security settings are changed. Packaged executables are not code-signed.

## Project layout and licenses

`hisser/` contains the UI, engine and exporters. `tests/` holds behavior tests; `scripts/` prepares, builds and updates the portable app. Runtime/model weights and large QA files are generated locally.

Hisser's own source is available under the [MIT License](LICENSE). Bundled models and third-party software retain their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md) and the notices included with the portable app. The MIT license does not replace those dependency licenses.

Maintainers: see [the release checklist](docs/RELEASING.md) before publishing a portable download. Do not upload your everyday app folder with personal settings, recordings or transcripts.
