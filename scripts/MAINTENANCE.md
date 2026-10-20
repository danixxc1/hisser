# Hisser portable maintenance

Daily use: open the branded **Hisser** desktop shortcut, or double-click **Hisser.exe** inside the portable folder. Keep the entire folder together when moving it. There is no installation or Python activation.

The frozen app resolves `data` beside its executable. `data\transcription-profile.json` selects a catalog model ID and CPU thread count; the matching model and verification metadata live in `data\models`. Settings and temporary work are also inside `data`. The only external app item is the branded Hisser desktop shortcut. No app registration or Start menu item is created.

To remove it, close Hisser, delete the entire portable folder and remove the Hisser desktop shortcut. Source media, exports saved outside that folder, the development project, global Python and other projects are separate. Windows' own history/security records are managed by Windows.

For developers, after using the isolated `.venv` and preparing the verified runtime:

```powershell
# First preparation: existing NVIDIA driver, no toolkit/driver installation.
.\.venv\Scripts\python.exe scripts\prepare_runtime.py --backend cuda
.\scripts\build.ps1 -Backend cuda
.\scripts\package-portable.ps1
```

For an update that reuses the existing portable model, prepare with `--backend cuda --skip-model` before rebuilding. To produce a CPU-only package, use `--backend cpu` and `build.ps1 -Backend cpu`; the build excludes CUDA binaries even if a comparison runtime exists locally. CUDA builds require both NVIDIA cuBLAS DLLs in addition to the official whisper.cpp CUDA engine. Preserve the complete bundled runtime and its licenses together.

The default remains `large-v3-q5_0`. A developer may prepare Turbo for comparison with `--model large-v3-turbo-q5_0 --model-directory 'qa\turbo-comparison\models'`. This also writes its profile beside that comparison model directory. Keep this separate from portable `data`; do not promote it until a person approves names, missing dialogue and meaning against the audio. Final packaging must retain exactly one model and its matching pinned metadata. Thread defaults come from the selected profile; performance evidence is recorded in `docs/PERFORMANCE.md`.

The default destination is `Tools\Hiss` under the current Windows user's Documents folder. To choose a different dedicated folder, pass `-Destination 'D:\My tools\Hiss'`. Desktop and local setup data paths are resolved from the current user's Windows known folders. No username is built into the scripts.

Preview packaging without changing files using `-WhatIf`. `install.ps1` is only a compatibility wrapper with the same parameters; it does not install/register an app.

The build creates `dist\Hisser`. Packaging stages that folder beside the selected destination, validates the selected profile and upstream model hash, moves the single data/model directory, and verifies startup, exports and backend dependencies before committing. The complete retained portable folder must remain **strictly below 4,000,000,000 bytes**. Downloads, temporary staging/rollback copies and decoded working audio need extra space. Failed deployment restores the prior folder/model when possible. An existing destination must carry the expected portable marker; unrecognized files at its root stop updates. The destination must be a dedicated folder outside the source project and protected Windows folders. Keep personal exports outside the app folder. Updates preserve the whole `data` directory.

The initial model download is temporarily at `%LOCALAPPDATA%\Hisser` during setup. Packaging moves that directory into the portable folder; no retained duplicate model is needed. On subsequent updates it reuses the portable `data` folder. If both setup and destination data exist, choose explicitly with `-DataDirectory`. To relocate an existing app's data, give a new `-Destination` plus the old app's `data` folder as `-DataDirectory`; this moves the data, so the old app cannot transcribe until you move it back. The former program folder is left intact for deliberate removal after checking the new copy.

Daily processing offers **Automatic / CPU**. Automatic tries the bundled NVIDIA runtime and reports the actual backend; a GPU initialization or memory failure retries once on CPU. Cancellation prevents the retry. CPU forces the separate CPU engine. Test both modes, cancellation and all five exports after an update; never report failed or cancelled work as completed.

After full acceptance, remove only setup-generated `dist`, `build`, duplicate workspace runtime binaries, downloaded archives and temporary fixtures. Keep the source, scripts, provenance/licenses, guide, and small QA reports. Keep local media/transcripts and comparison models out of Git. If runtime copies were removed, restore them from portable `_internal\runtime` for a later rebuild, or rerun verified preparation with the chosen `--backend` plus `--skip-model` to avoid another model copy.
