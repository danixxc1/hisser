# Testing Hisser

The automated suite runs on Windows with Python 3.14. It uses generated fixtures and small fake worker programs; no real model, personal recording or network request is needed during tests. Native Tk windows stay withdrawn. GitHub Actions installs the pinned development dependencies, then runs the same suite.

From a clean checkout in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q --basetemp=qa/test-run
```

Pytest clears its selected `--basetemp` directory at the next run; use only a disposable test path there.

The tests cover canonical text/timings in all five exports; Unicode and embedded-font PDF pagination; overwrite confirmation, late-created destinations and rollback; missing/corrupt media/model; subprocess cancellation and retry; temporary cleanup; quiet samples and exact-zero silence mapping; and UI states. PDF extraction checks are supplemented by visual rendering during local acceptance.

## Actual model acceptance

These optional tests use the approved local Whisper model and Windows System.Speech to create explicitly synthetic English. They can take several minutes and are separate from CI. Supply paths to an already prepared runtime and model; the runner does not download them.

```powershell
.\.venv\Scripts\python.exe scripts/acceptance_engine.py --short --auto --failures --long --runtime-directory '<portable-folder>\_internal\runtime' --model '<portable-folder>\data\models\ggml-large-v3-q5_0.bin'
```

`--output-directory` selects the local report/fixture folder (default `qa/engine-integration`). `--powershell` selects a Windows PowerShell/pwsh executable with System.Speech; `--voice` selects an installed English voice (default Microsoft Zira Desktop). The runner refuses to start while another whisper-cli process is running. Keep reports, recordings and machine-specific provenance local; they can contain full file paths and recognized words.

Measured on the original Windows 11 laptop, with two CPU inference threads, one processor and below-normal process priority:

| Synthetic check | Result |
|---|---|
| 14.032-second clear English sample | Known phrase recognized; 72.985 seconds; peak recognition RSS about 2.09 GB |
| Auto-language detection on that sample | Detected `en`; 108.415 seconds; source SHA-256 unchanged |
| Complete 30:38.523 recording with late speech | Phrase after minute 30 recognized with original-source timing |
| Missing/corrupt inputs/model, no audio, cancellation, retry | All seven actual acceptance cases passed; temporary jobs cleaned |
| PDF/SRT/TXT/VTT/JSON from actual recognized words | Shared canonical text/timing verified; PDF visually checked |

The long fixture contains exact digital silence until 30:30, then synthetic spoken words. The app decodes and scans the complete file, trims only long exact-zero outer spans, recognizes the retained audio once, and maps timestamps back to the full source. This is evidence that late speech is included, not a continuous 30-minute speech benchmark. Film and Tagalog accuracy remain untested. Timings and memory are measurements from that laptop and can differ elsewhere.

## Runtime preparation

`scripts/prepare_runtime.py` pins the CPU whisper.cpp archive and multilingual `ggml-large-v3-q5_0.bin` model by upstream revision, SHA-256 and size. `--model-directory` can target a portable folder's `data\models`; otherwise it uses the current user's `%LOCALAPPDATA%\Hisser\models`. Existing valid model files are reused. `--skip-model` prepares only runtime files and retains the approved model metadata in provenance without claiming a model verification.

Preparation copies an existing matching FFmpeg/ffprobe pair from PATH and records its actual version, build configuration and license. The initial build used FFmpeg 9.0.2. It copies the required Microsoft-signed CPU runtime DLLs from the Windows system; it does not install a GPU toolkit, change drivers, or change global Python. Model/runtime downloads and their generated provenance are excluded from Git. Windows Security scans are attempted unless explicitly skipped, and scan failures are recorded as unconfirmed rather than reported clean.

For the approved model, the fixed revision is `5359861c739e955e79d9a303bcbc70fb988958b1`, size `1,081,140,203` bytes, SHA-256 `d75795ecff3f83b5faa89d1900604ad8c780abd5739fae406de19f23ecd98ad1`. Preparation verifies upstream metadata against those constants and refuses a changed model.
