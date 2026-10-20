# Publishing a portable Windows release

The user download belongs in **GitHub Releases**. The Git repository contains source and build instructions; **Code → Download ZIP** does not include a runnable app, model or runtime. Keep large generated binaries out of Git and Git LFS.

## Prepare the release

1. Choose the version in `hisser/__init__.py` and update the user guide, performance report and release notes for the actual configuration.
2. Run the locked-dependency check and full test suite in README.md. Require Windows CI to pass for the exact source commit being released.
3. Prepare the pinned runtime and one approved model, then build and validate the portable app using the source-build instructions. Verify upstream hashes and security-scan results. Review the third-party redistribution notices and include their required licenses and corresponding-source information in the downloadable package.
4. Use `scripts/package-release.py` to create the shareable package from an allowlist of app/runtime/model files. Start with fresh default settings and an empty temporary directory. Do not ZIP an everyday working folder indiscriminately: it can contain personal paths, settings or recordings.
5. Confirm the extracted app is below **4,000,000,000 bytes**. Include exactly one selected model and its verification metadata, the transcription profile, user guide and third-party notices. Include neither an absolute-path desktop shortcut nor a user's transcripts, media, comparison clips, credentials, logs, development environment or build caches.

The default released configuration is **large-v3 Q5**, **Automatic** processing and **six CPU threads**. Automatic uses the bundled CUDA runtime when available and falls back to CPU as documented. Turbo is not the selected release model.

For the public redistribution runtime, manually run **Build public distribution runtime** (`.github/workflows/release-runtime.yml`) at the reviewed source commit. It uses the hosted Windows runner's existing licensed Visual Studio Enterprise redistributable directories and compiles the hash-pinned official FFmpeg 9.0.2 source with native codecs, LGPL configuration and local-file processing. The build records the selected Visual Studio version and its matching redistribution terms. It does not publish a release. Download its **hisser-distribution-runtime** artifact and review its hashes, Microsoft signatures, FFmpeg license/configuration and source archive before use. Details are in [distribution requirements](DISTRIBUTION.md).

For example, after completing the build and third-party licensing checks, substitute the path to the validated portable app:

```powershell
.\.venv\Scripts\python.exe scripts\package-release.py `
  --source-directory 'D:\Tools\Hiss' `
  --output-directory 'qa\release' `
  --version 1.1.0 `
  --runtime-overlay 'qa\distribution-runtime\runtime-overlay'
```

The packager's default legal directory is the repository's `licenses` folder; `--legal-directory` can explicitly select another reviewed legal bundle. Keep the output directory ignored by Git and upload only the final reviewed assets. Publish the unchanged **ffmpeg-9.0.2-source.tar.gz** alongside the app and a **ffmpeg-build-source.zip** containing its build scripts, generated configuration, license and build reports from `corresponding-source`. Include checksums for both source assets.

## Verify the downloadable artifact

Use a ZIP containing one top-level **Hisser** folder, with **Hisser.exe**, **_internal** and **data** beneath it. Use the asset name **Hisser-1.1.0-windows-x64.zip**, changing the version for future releases.

[GitHub limits an individual release asset to less than 2 GiB](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases). Check the compressed ZIP's actual size before uploading. The expanded app can be larger; do not confuse that with the release asset limit. If it exceeds the asset limit, stop and revise the packaging strategy before publishing user instructions that promise a single ZIP.

Extract the exact ZIP to a clean writable test folder. Confirm that the package:

- Starts by double-clicking the EXE, without a development environment, Python activation or paths back to the maintainer's machine.
- Loads its bundled large-v3 model, uses Automatic/CPU as selected, supports cancellation and explains a GPU failure before its one CPU retry.
- Transcribes a short local input and saves PDF, SRT, TXT, VTT and JSON, including Unicode names and paths.
- Writes settings and job files only to its portable `data` directory and cleans temporary job files after completion, cancellation or failure.
- Contains no personal material. Generated provenance should contain upstream identifiers and hashes, with local account paths removed.

Record which hardware and Windows version were actually tested; do not claim the same speed or memory behavior on every computer. Keep real user recordings and their transcripts local and excluded from both Git and release assets.

Compute SHA-256 for the finished ZIP and put the exact digest and filename in **Hisser-1.1.0-windows-x64.zip.sha256**. Include checksums for any additional downloadable companion assets. A checksum establishes consistency with the published artifact; it is not a signature or a guarantee of safety. The current EXE is unsigned, which must be stated in release notes and download instructions.

## Publish

Create a version tag such as **v1.1.0** at the reviewed source commit and a matching GitHub release. Attach the verified ZIP, its matching **.sha256** file and any license-required companion source archive. Publish only after the artifact and notices are complete. Do not upload test recordings or a development folder.

Use release notes that tell a recipient:

- Download the Windows x64 ZIP under **Assets**, choose **Extract All…**, open the **Hisser** folder and run **Hisser.exe**. Keep the folder together.
- Python, Git, an API key, a separate FFmpeg installation and administrator access are not required for normal use.
- Windows 10/11 x64 is the target; Windows 11 with 16 GB RAM was tested. Recommend 8 GB free storage for download, extraction and working space. Describe compatible existing NVIDIA drivers and CPU fallback without promising support for untested hardware.
- State the actual download size, extracted size, bundled model, version and measured-performance limitations. Link the checksum instructions and third-party notices.
- Explain that the EXE is unsigned and recommend verifying its origin/checksum while keeping security protections enabled.
- To remove the app, close it and delete its extracted folder and any shortcut; separately delete the downloaded ZIP if desired. Exported transcripts saved elsewhere remain.

After publishing, open the release page and verify its asset names, sizes, checksums and download links. Confirm README.md's latest-release link reaches the intended release.

## Repository access

A public repository lets recipients download releases without a collaborator invitation. Review the complete source and Git history for private material before changing visibility, because the change exposes history as well as current files. If visibility is later changed to private, its releases require an authorized, signed-in GitHub account; a release URL alone will not grant access.

Hisser's own source uses the MIT License selected by its owner. Include the committed LICENSE file in the portable package. Third-party runtime and model licenses apply independently; do not label the entire dependency bundle as MIT.
