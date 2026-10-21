# Distributing Hisser

The downloadable Windows app belongs in a versioned GitHub Release asset. GitHub's automatic **Source code (zip)** contains the development source and is not the runnable app. Keep executable files, model weights, generated data and personal recordings out of Git history.

A release contains a clean `Hisser/` folder with `Hisser.exe`, `_internal/`, the selected model in `data/models/`, its verified profile, instructions, complete third-party notices and a file manifest. Recipients extract the entire folder before running `Hisser.exe`. Use fresh default settings; exclude recordings, transcripts, job history, temporary files and machine-specific paths.

## FFmpeg source and licenses

The selected release uses FFmpeg/ffprobe **`n9.0.2-31-gc89d6ee1ca-20261021`** from BtbN's [pinned Windows x64 LGPL build](https://github.com/BtbN/FFmpeg-Builds/releases/tag/autobuild-2026-10-21-13-06). The binary archive is **`ffmpeg-n9.0.2-31-gc89d6ee1ca-win64-lgpl-9.0.zip`**, SHA-256 **`1840634b3f2ce1512d9208f1ea96084bed42cf4b80a94546ff1a8757a594e389`**. Include only its unmodified ffmpeg and ffprobe programs; ffplay is not required. Their reported license is **LGPL 3 or later**. Hisser launches them as separate processes; its Python application does not link to FFmpeg libraries.

The FFmpeg source is [commit `c89d6ee1ca848314270155ceb13b1cab3744fc3c`](https://github.com/FFmpeg/FFmpeg/tree/c89d6ee1ca848314270155ceb13b1cab3744fc3c), and the matching [BtbN build recipes](https://github.com/BtbN/FFmpeg-Builds/tree/63ac3265b0789ea16c7b1f8351cd2ad195a28722) are pinned at `63ac3265b0789ea16c7b1f8351cd2ad195a28722`. Preserve the dependency source cache from the same upstream workflow run, **39598082585**, artifact **12345526726**. Match the enabled libraries against the actual `-buildconf` output and recipes; a generic FFmpeg source archive alone is insufficient for these statically linked programs.

Publish checksum-identified corresponding-source companion archives beside the runnable app. They must contain the exact FFmpeg source, enabled dependency sources and patches, build recipes, configuration/compiler records, complete license texts and applicable notices. Link them from the release description and preserve them when maintaining older releases. Preserve recipients' rights to inspect, modify and rebuild those components under their licenses. See [FFmpeg's official licensing guidance](https://ffmpeg.org/legal.html).

The repository also retains an optional native-only MSVC build in **Build public distribution runtime** (`.github/workflows/release-runtime.yml`). Its FFmpeg output was rejected by Windows application-control policy on the tested laptop, so that output is not the selected public media runtime. The workflow remains useful for obtaining the reviewed Microsoft redistributables and for future build investigation. Any future media replacement needs its own source/licensing record and complete pipeline checks with security protections enabled.

The personal runtime's Gyan full-build executables are not release inputs. Do not substitute a different upstream build while retaining the BtbN source or license record.

## Microsoft runtime provenance

Release builds obtain the needed unmodified app-local CRT/OpenMP files from Visual Studio's `VC/Redist` directories on the GitHub-hosted Windows runner. Record the Visual Studio edition/version, applicable license and redistributable list, runner image, file hashes and signatures. Exclude debug and other nonredistributable files. Microsoft permits this distribution subject to its Visual Studio terms; see [Microsoft's redistribution guidance](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files).

The [runner image maintainers confirm](https://github.com/actions/runner-images/issues/12945#issuecomment-3348002951) that their Enterprise license arrangement covers public and private hosted-runner use without a separate user license. This evidence concerns GitHub-hosted runners; it does not grant a license for a separate local or self-hosted Visual Studio installation. No global runtime installation is required on the recipient's computer. Signed System32 copies from a personal machine are not release provenance.

## NVIDIA runtime

CUDA 11.8's redistribution list includes the versioned Windows CUDA runtime, cuBLAS/cuBLASLt and NVRTC/NVRTC-builtins libraries used here. Bundle them only as dependencies of Hisser, retain the full supplied license and third-party notices, and keep the distribution terms consistent with NVIDIA's agreement. Do not redistribute developer tools or a driver as part of the portable app. See [CUDA 11.8 EULA, distribution requirements and Attachment A](https://docs.nvidia.com/cuda/archive/11.8.0/eula/index.html).

The accompanying NVIDIA notice states that these libraries are supplied for Hisser's GPU processing, remain subject to NVIDIA's agreement and are not provided as a standalone SDK. Hisser's MIT source license does not relicense them. Retain that notice and the complete NVIDIA license when sharing the app folder.

## Release record

Before publishing, record the app/source version, dependency and model hashes, license inventory, scan result, extracted size below **4,000,000,000 bytes**, and a SHA-256 checksum for each downloadable asset. Include corresponding source assets with the same release and link them from its description. Test a newly extracted copy with Unicode paths, a real media file, CPU processing, GPU processing when available, cancellation, fallback and all five exports.

Public release assets can be downloaded without a GitHub account. A private release requires authorized GitHub access. Changing repository visibility requires the owner's explicit instruction. Keep a release in draft while any dependency's redistribution provenance or required source is unresolved.
