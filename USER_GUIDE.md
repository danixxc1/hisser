# Using Hisser

Open **Hisser.exe** in your portable **Hiss** folder, or double-click the **Hisser** desktop shortcut. No installation or Python activation is needed. Keep the entire folder together when moving it; recreate the shortcut afterward.

1. Select **Choose file…** and pick a local audio or video file.
2. Choose **Auto-detect**, **Tagalog / Filipino**, **English**, or another language.
3. Select **Transcribe**. The first job loads the model. **Cancel** stops the job and removes its temporary audio.
4. Read/select the transcript, or use **Copy text**.
5. Select any combination of **PDF, SRT, TXT, VTT, JSON**, then **Save transcript…**. One format opens Save As; several use a folder. Existing files need confirmation. Saving another format does not run recognition again.

The source stays unchanged. Transcription uses the original language, without translation. Processing stays on this computer after setup. There is no recording-length or daily quota.

## Working space and accuracy

Decoded audio needs about **115 MB per hour** in additional temporary space. Silence trimming may briefly need another copy. Job files are removed after completion, failure or cancellation. Recognition needs several GB of RAM and can take longer than the recording; close heavy applications if memory is tight.

Start with a short sample. Synthetic English checks do not establish film or Tagalog accuracy. Names, mixed languages, music and overlapping dialogue need review against the recording. Unsaved transcripts live only in the current window; save before closing or choosing another file.

## Errors and retry

- The recording needs a decodable audio track. Select another playable local file if it is missing or corrupt.
- If recognition runs out of memory, close memory-heavy apps, then select **Retry**.
- Keep `_internal` beside the EXE and the verified model in `data\models`. Restore the complete portable folder if program files are missing. There is no automatic model upgrade.
- If saving fails, keep the preview open and choose a writable output folder.

## Remove Hisser

Close the app, delete its entire portable **Hiss** folder, then delete the **Hisser** desktop shortcut. The EXE, runtime, downloaded model, settings, cache and temporary job files all live in that folder. There is no Windows app registration.

The development project, source recordings and transcripts saved outside the app folder stay untouched. Empty the Recycle Bin to reclaim space. Global Python, Mama, drivers and other apps are not changed. Windows manages its own shared history/security records.

## Update or repair

The model and settings live in `data` beside the EXE. Developer packaging scripts preserve that directory while updating program files. See README.md and scripts/MAINTENANCE.md in the source project. Normal daily use only requires the EXE or shortcut.
