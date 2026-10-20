# Testing Hisser

The automated suite runs on Windows with Python 3.14. It uses generated fixtures and small fake worker programs; no real model, personal recording or network request is needed during tests. Native Tk windows stay withdrawn. GitHub Actions installs the pinned development dependencies, then runs the same suite.

From a clean checkout in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest-work
```

Pytest clears its selected `--basetemp` directory at the next run; use only a disposable test path there.

The tests cover canonical text/timings in all five exports; Unicode and embedded-font PDF pagination; overwrite confirmation, late-created destinations and rollback; missing/corrupt media/model; subprocess cancellation and retry; temporary cleanup; quiet samples and exact-zero silence mapping; verified model profiles; Automatic/CPU selection; GPU loader/init/memory fallback; cancellation during fallback; CPU failure propagation; and UI states. PDF extraction checks are supplemented by visual rendering during local acceptance.

## Actual model acceptance

These optional tests use the approved local Whisper model and Windows System.Speech to create explicitly synthetic English. They can take several minutes and are separate from CI. Supply paths to an already prepared runtime and model; the runner does not download them.

```powershell
.\.venv\Scripts\python.exe scripts/acceptance_engine.py --short --auto --failures --long --runtime-directory '<portable-folder>\_internal\runtime' --model '<portable-folder>\data\models\ggml-large-v3-q5_0.bin'
```

For GPU acceptance, append `--processing auto --threads 6` and select a fresh `--output-directory`. `--fixtures-directory` can reuse the existing dedicated synthetic fixture folder. The runner records the selected model descriptor and actual backend, and verifies real cancellation, retry and late speech with original-source timestamps.

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

`scripts/prepare_runtime.py` pins the CPU/CUDA whisper.cpp archives, required NVIDIA cuBLAS redistribution and selected model by upstream revision, SHA-256 and size. See [runtime inputs](../runtime/README.md). `--backend cuda` adds the optional GPU files without installing a driver or toolkit; `--model large-v3-turbo-q5_0` selects the comparison candidate. The default model remains large-v3. `--model-directory` can target a portable folder's `data\models`; otherwise it uses the current user's `%LOCALAPPDATA%\Hisser\models`. Existing valid model files are reused. `--skip-model` prepares only runtime files and retains the selected model metadata in provenance without claiming a model verification.

Preparation copies an existing matching FFmpeg/ffprobe pair from PATH and records its actual version, build configuration and license. The initial build used FFmpeg 9.0.2. It copies the required Microsoft-signed CPU runtime DLLs from the Windows system; it does not install a GPU toolkit, change drivers, or change global Python. Model/runtime downloads and their generated provenance are excluded from Git. Windows Security scans are attempted unless explicitly skipped, and scan failures are recorded as unconfirmed rather than reported clean.

For the approved model, the fixed revision is `5359861c739e955e79d9a303bcbc70fb988958b1`, size `1,081,140,203` bytes, SHA-256 `d75795ecff3f83b5faa89d1900604ad8c780abd5739fae406de19f23ecd98ad1`. Preparation verifies upstream metadata against those constants and refuses a changed model.

## Serial speed comparison

Use `scripts/benchmark_speed.py --help` for the optional local runner. Supply explicit runtime/model paths, a local source video and the existing English fixture. `prepare` creates three local 30-second excerpts; the current default offsets are 300, 2800 and 5100 seconds, so use an appropriate long recording. `threads` compares 2/4/6/8 CPU threads and selects the fewest within 5% of the fastest wall time. `matrix` compares large-v3 CPU/GPU and Turbo CPU/GPU, sequentially. Repeated `--config` arguments can select a subset. `report` creates local listening comparisons; successful prior runs can be resumed, or deliberately repeated with `--rerun`.

Normal beam/best-of defaults remain five; no new voice filtering or reduced-quality decoding is used. Each run records source hashes, startup-to-processing, CLI timing, process RAM and whole-GPU memory samples. Whole-GPU measurements include other apps and are not exact per-process VRAM on Windows. GPU log evidence is required to report GPU success. Missing/deleted original videos are marked unavailable rather than claimed preserved; saved excerpt hashes remain verifiable.

Reports, audio, transcript text and machine paths remain under ignored `qa/`. Publish only aggregate measurements. Read [the performance report](PERFORMANCE.md) for current results and limits. A human must listen for names, omissions and meaning-changing mistakes before Turbo replaces large-v3. Replacement videos receive a fresh fixture manifest rather than overwriting earlier evidence.

With both verified models and the CPU/CUDA runtime already prepared, run the following from the repository root. Paste full input paths when prompted. Choose a video at least 85 minutes 30 seconds long for the default excerpt positions; use a fresh output directory for each source.

```powershell
$comparisonVideo = Read-Host 'Full path to the local source video'
$englishFixture = Read-Host 'Full path to the known synthetic English WAV'
$benchmarkPaths = @(
  '--cpu-runtime', (Resolve-Path './runtime').Path,
  '--cuda-runtime', (Resolve-Path './runtime/cuda').Path,
  '--large-model', (Read-Host 'Full path to verified ggml-large-v3-q5_0.bin'),
  '--turbo-model', (Read-Host 'Full path to verified ggml-large-v3-turbo-q5_0.bin'),
  '--output-directory', './qa/speed-local'
)
./.venv/Scripts/python.exe scripts/benchmark_speed.py prepare @benchmarkPaths --film $comparisonVideo --english $englishFixture
./.venv/Scripts/python.exe scripts/benchmark_speed.py threads @benchmarkPaths
./.venv/Scripts/python.exe scripts/benchmark_speed.py matrix @benchmarkPaths
./.venv/Scripts/python.exe scripts/benchmark_speed.py report @benchmarkPaths
Start-Process './qa/speed-local/COMPARE.html'
```

For a staged run, append `--config large-cpu --config turbo-cpu` to `matrix`, then run it again with `--config large-cuda --config turbo-cuda`. It reuses successful prior results only when excerpt, model and CLI SHA-256 hashes, backend, language, thread count and decoding profile match. Older reports without these fingerprints must be measured again. `--reuse-from <earlier-report-folder>` can link matching measurements for a replacement source; each linked report records the original measurement and explicitly states that recognition was not rerun. Use `--rerun` to force a new measurement. GPU success requires positive CUDA-backend log evidence. Timed-out or failed jobs remain failures, and the runner terminates only its own child process.
