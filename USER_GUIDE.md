# Using Hisser

Download the Windows x64 ZIP from the project's [GitHub Releases](https://github.com/danixxc1/hisser/releases/latest), choose **Extract All…**, then open **Hisser.exe** in the extracted **Hisser** folder. The repository's **Code → Download ZIP** is developer source, not the ready-to-run app.

No installation, administrator access, Python, Git, FFmpeg setup, API key or cloud account is needed for normal use. Keep the entire folder together when moving it. You can create a desktop shortcut to the extracted EXE; recreate it after moving the folder. Run Hisser from a folder you can write to, such as Documents.

Windows 11 x64 with 16 GB RAM was tested. Windows 10/11 x64 is the release target; ARM64 and 32-bit Windows are not tested. Allow 8 GB free disk space for the ZIP, extraction and working space. A compatible NVIDIA GPU can accelerate processing through its existing driver; CPU processing is available too.

1. Select **Choose file…** and pick a local audio or video file.
2. Choose **Auto-detect**, **Tagalog / Filipino**, **English**, or another language.
3. Leave **Processing** on **Automatic** to try NVIDIA GPU acceleration, or choose **CPU**. Select **Transcribe**. The first job loads the model. **Cancel** stops the job and removes its temporary audio.
4. Read/select the transcript, or use **Copy text**.
5. Select any combination of **PDF, SRT, TXT, VTT, JSON**, then **Save transcript…**. One format opens Save As; several use a folder. Existing files need confirmation. Saving another format does not run recognition again.

The source stays unchanged. Transcription uses the original language, without translation. Processing stays on this computer after setup. There is no recording-length or daily quota.

**Automatic** uses the optional GPU runtime when available. If GPU initialization or GPU memory fails, Hisser tells you and retries once on CPU. Cancelling stops the job without retrying. The progress area shows the model and processing actually used. A CPU-only package works without an NVIDIA GPU. No driver or GPU toolkit is installed.

## Download verification

Download the matching **.zip.sha256** file from the same GitHub release as the app ZIP. In PowerShell, use the actual path of your downloaded ZIP:

```powershell
Get-FileHash -LiteralPath "$env:USERPROFILE\Downloads\Hisser-1.1.0-windows-x64.zip" -Algorithm SHA256
```

Compare the complete hash with the entry for that ZIP in its **.sha256** file. The characters must match; letter case does not matter. A matching hash checks that the file matches the published release, rather than proving the app is safe. If it differs, do not run the download; download it again from the release page.

Hisser is not code-signed. Windows may warn about an unfamiliar publisher or download. Verify the release origin and checksum, keep Windows security protections enabled, and only run the app if you trust its source.

## Working space and accuracy

The extracted public release is approximately **2.45 GB**, retains one model and stays **below 4 GB**. Decoded audio needs about **115 MB per hour** in additional temporary space. Silence trimming may briefly need another copy. Job files are removed after completion, failure or cancellation. Recognition needs several GB of RAM and can take longer than the recording, especially on CPU; close heavy applications if memory is tight.

Start with a short sample. Synthetic English checks do not establish film or Tagalog accuracy. Names, mixed languages, music and overlapping dialogue need review against the recording. Unsaved transcripts live only in the current window; save before closing or choosing another file.

The default remains the large-v3 model. Turbo is a smaller comparison option for a developer to test; switching to it requires reviewing its wording against the audio first. Model compression reduces disk space, not the need to check accuracy. Measured comparisons are in `docs/PERFORMANCE.md` in the source project.

## Errors and retry

- The recording needs a decodable audio track. Select another playable local file if it is missing or corrupt.
- If recognition runs out of memory, close memory-heavy apps, then select **Retry**.
- If Automatic reports a GPU failure, allow its one CPU retry. Choose **CPU** for the next job if GPU failures persist.
- Keep `_internal` beside the EXE and the verified model in `data\models`. Restore the complete portable folder if program files are missing. There is no automatic model upgrade.
- If the transcription profile or model verification record is missing or damaged, restore the verified package; renaming a different model is not a repair.
- If saving fails, keep the preview open and choose a writable output folder.

## Remove Hisser

Close the app, delete its entire extracted portable folder, then delete any **Hisser** desktop shortcut you created. The EXE, runtime, downloaded model, settings, cache and temporary job files all live in that folder. There is no Windows app registration.

The development project, source recordings and transcripts saved outside the app folder stay untouched. Delete any downloaded release ZIP too if you no longer need it, and empty the Recycle Bin to reclaim space. Drivers and other apps are not changed. Windows manages its own shared history/security records.

## Update or repair

Close Hisser, download the new release and extract it to a new folder. Check its checksum, then run the new EXE and test a short recording before deleting the old folder. Keep your saved transcripts outside the app folder. Each release contains its own verified model and profile; avoid mixing `_internal` or `data\models` from different releases. Recreate your desktop shortcut to point to the new EXE.

The model, verification metadata, selected transcription profile and settings live in `data` beside the EXE. Maintainers using the developer packaging scripts can preserve that directory during an update; see README.md and scripts/MAINTENANCE.md in the source project. Normal daily use only requires the EXE or shortcut.
