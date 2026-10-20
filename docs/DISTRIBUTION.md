# Distributing Hisser

The downloadable Windows app belongs in a versioned GitHub Release asset. GitHub's automatic **Source code (zip)** contains the development source and is not the runnable app. Keep executable files, model weights, generated data and personal recordings out of Git history.

A release contains a clean `Hisser/` folder with `Hisser.exe`, `_internal/`, the selected model in `data/models/`, its verified profile, instructions, complete third-party notices and a file manifest. Recipients extract the entire folder before running `Hisser.exe`. Use fresh default settings; exclude recordings, transcripts, job history, temporary files and machine-specific paths.

## FFmpeg source and licenses

Release builds compile FFmpeg/ffprobe 9.0.2 from [official commit `946fcce07b6dcd0331c8cc609192aeff5e1924f8`](https://github.com/FFmpeg/FFmpeg/tree/946fcce07b6dcd0331c8cc609192aeff5e1924f8), using the Windows runner's MSVC compiler. The commit's source tarball has SHA-256 `0aa2b1de2a5698b20a23e93d539a9a8e82ca0117496c5bdf05d198805f42bb3b`. GPL components, nonfree components, optional external libraries and automatic external-library detection are disabled. The resulting command-line programs use LGPL 2.1 or later. Hisser launches them as separate processes; its Python application does not link to FFmpeg libraries.

Keep the exact source archive, build script, configuration, compiler details, modifications if any, and LGPL text with the release's corresponding-source download. Publish it beside the runnable app and link both from the release description. Preserve the source and asset checksums when maintaining an older release. See [FFmpeg's official licensing guidance](https://ffmpeg.org/legal.html).

The existing personal runtime's Gyan full-build executables are not inputs to this release workflow. That build enables many external libraries and GPLv3; redistributing it would require the matching sources and notices for those dependencies too. A bare FFmpeg source-tree link or upstream download link does not establish complete source availability for that build.

## Microsoft runtime provenance

Release builds obtain the needed unmodified app-local CRT/OpenMP files from Visual Studio's `VC/Redist` directories on the GitHub-hosted Windows runner. Record the Visual Studio edition/version, applicable license and redistributable list, runner image, file hashes and signatures. Exclude debug and other nonredistributable files. Microsoft permits this distribution subject to its Visual Studio terms; see [Microsoft's redistribution guidance](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files).

The [runner image maintainers confirm](https://github.com/actions/runner-images/issues/12945#issuecomment-3348002951) that their Enterprise license arrangement covers public and private hosted-runner use without a separate user license. This evidence concerns GitHub-hosted runners; it does not grant a license for a separate local or self-hosted Visual Studio installation. No global runtime installation is required on the recipient's computer. Signed System32 copies from a personal machine are not release provenance.

## NVIDIA runtime

CUDA 11.8's redistribution list includes the versioned Windows CUDA runtime, cuBLAS/cuBLASLt and NVRTC/NVRTC-builtins libraries used here. Bundle them only as dependencies of Hisser, retain the full supplied license and third-party notices, and keep the distribution terms consistent with NVIDIA's agreement. Do not redistribute developer tools or a driver as part of the portable app. See [CUDA 11.8 EULA, distribution requirements and Attachment A](https://docs.nvidia.com/cuda/archive/11.8.0/eula/index.html).

The accompanying NVIDIA notice states that these libraries are supplied for Hisser's GPU processing, remain subject to NVIDIA's agreement and are not provided as a standalone SDK. Hisser's MIT source license does not relicense them. Retain that notice and the complete NVIDIA license when sharing the app folder.

## Release record

Before publishing, record the app/source version, dependency and model hashes, license inventory, scan result, extracted size below **4,000,000,000 bytes**, and a SHA-256 checksum for each downloadable asset. Include corresponding source assets with the same release and link them from its description. Test a newly extracted copy with Unicode paths, a real media file, CPU processing, GPU processing when available, cancellation, fallback and all five exports.

Public release assets can be downloaded without a GitHub account. A private release requires authorized GitHub access. Changing repository visibility requires the owner's explicit instruction. Keep a release in draft while any dependency's redistribution provenance or required source is unresolved.
