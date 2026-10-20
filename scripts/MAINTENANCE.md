# Hisser portable maintenance

Daily use: open the branded **Hisser** desktop shortcut, or double-click **Hisser.exe** inside the portable folder. Keep the entire folder together when moving it. There is no installation or Python activation.

The frozen app resolves `data` beside its executable. Its model is `data\models\ggml-large-v3-q5_0.bin`; settings and temporary work are also inside `data`. The only external app item is the branded Hisser desktop shortcut. No app registration or Start menu item is created.

To remove it, close Hisser, delete the entire portable folder and remove the Hisser desktop shortcut. Source media, exports saved outside that folder, the development project, global Python and other projects are separate. Windows' own history/security records are managed by Windows.

For developers, after using the isolated `.venv` and preparing the verified runtime:

```powershell
.\scripts\build.ps1
.\scripts\package-portable.ps1
```

The default destination is `Tools\Hiss` under the current Windows user's Documents folder. To choose a different dedicated folder, pass `-Destination 'D:\My tools\Hiss'`. Desktop and local setup data paths are resolved from the current user's Windows known folders. No username is built into the scripts.

Preview packaging without changing files using `-WhatIf`. `install.ps1` is only a compatibility wrapper with the same parameters; it does not install/register an app.

The build creates `dist\Hisser`. Packaging stages that folder beside the selected destination, validates the upstream model hash, moves the single data/model directory, and verifies startup before committing. Failed deployment restores the prior folder/model when possible. An existing destination must carry the expected portable marker; unrecognized files at its root stop updates. The destination must be a dedicated folder outside the source project and protected Windows folders. Keep personal exports outside the app folder. Updates preserve the whole `data` directory.

The initial model download is temporarily at `%LOCALAPPDATA%\Hisser` during setup. Packaging moves that directory into the portable folder; no retained duplicate model is needed. On subsequent updates it reuses the portable `data` folder. If both setup and destination data exist, choose explicitly with `-DataDirectory`. To relocate an existing app's data, give a new `-Destination` plus the old app's `data` folder as `-DataDirectory`; this moves the data, so the old app cannot transcribe until you move it back. The former program folder is left intact for deliberate removal after checking the new copy.

After full acceptance, remove only setup-generated `dist`, `build`, duplicate workspace runtime binaries and temporary fixtures. Keep the source, scripts, provenance/licenses, guide, and small QA reports. If runtime copies were removed, restore them from the portable `_internal\runtime` for a later rebuild, or rerun verified preparation with `--skip-model` to avoid another model copy.
