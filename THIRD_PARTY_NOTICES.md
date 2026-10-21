# Third-party components

Hisser's own source is licensed under the [MIT License](LICENSE). The components below retain their separate licenses. The source repository excludes executable runtime binaries, model weights and private test recordings. Downloadable app releases carry the applicable complete license texts and corresponding source materials described in [Distribution](docs/DISTRIBUTION.md).

| Component | Purpose | Upstream license/source |
| --- | --- | --- |
| whisper.cpp b5454 (source commit `d1be6fde11ac6e0407606b4e42fe72d34add8037`) | CPU and NVIDIA CUDA speech recognition | [MIT](https://github.com/ggml-org/whisper.cpp/blob/b5454/LICENSE) |
| Whisper large-v3 / large-v3-turbo, GGML Q5_0 | Selected multilingual recognition model | [OpenAI Whisper MIT](https://github.com/openai/whisper/blob/main/LICENSE), [GGML distribution](https://huggingface.co/ggerganov/whisper.cpp) |
| NVIDIA CUDA 11.8 / cuBLAS 11.11.3.6 | Optional GPU runtime libraries | [CUDA toolkit license](https://docs.nvidia.com/cuda/archive/11.8.0/eula/index.html); see bundled NVIDIA-CUDA-cuBLAS-LICENSE.txt |
| FFmpeg / ffprobe `n9.0.2-31-gc89d6ee1ca-20261021` | Media inspection and decoding | [BtbN Windows x64 LGPL build](https://github.com/BtbN/FFmpeg-Builds/releases/tag/autobuild-2026-10-21-13-06), under LGPL 3 or later, from [FFmpeg commit `c89d6ee1ca848314270155ceb13b1cab3744fc3c`](https://github.com/FFmpeg/FFmpeg/tree/c89d6ee1ca848314270155ceb13b1cab3744fc3c). The exact FFmpeg source, enabled dependency sources, pinned build recipes and applicable notices accompany the release; see [FFmpeg license information](https://ffmpeg.org/legal.html). |
| Microsoft Visual C++ / OpenMP DLLs | Native runtime dependencies | Unmodified app-local files from Visual Studio's redistributable directories on the Windows build runner, under [Microsoft redistribution terms](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files). The release provenance identifies the Visual Studio version and its matching [redistributable file list](https://learn.microsoft.com/en-us/visualstudio/releases/2026/redistribution). |
| Python / Tk | Packaged language and native UI runtime | [Python license](https://docs.python.org/3/license.html), [Tcl/Tk license](https://www.tcl.tk/software/tcltk/license.html) |
| ReportLab | PDF generation | [ReportLab BSD license](https://hg.reportlab.com/hg-public/reportlab/file/tip/LICENSE.txt) |
| Pillow | Image support | [HPND license](https://github.com/python-pillow/Pillow/blob/main/LICENSE) |
| charset-normalizer | Text encoding support | [MIT](https://github.com/jawah/charset_normalizer/blob/master/LICENSE) |
| PyInstaller | Folder packaging | [GPL with bootloader exception](https://pyinstaller.org/en/stable/license.html) |

Windows Segoe UI is read from the local Windows Fonts folder for PDF embedding; font files are not committed to the repository. PDF support is intended for Filipino names and Latin accents. Not every script supported by Whisper has been font-tested.

The NVIDIA libraries remain under NVIDIA's terms and are supplied only for Hisser's GPU processing. They are not licensed under any Hisser or FFmpeg license. Use of these components is subject to the included NVIDIA license. They are not supplied as a standalone SDK or library package. The bundle does not include a GPU driver or CUDA development toolkit.

FFmpeg and ffprobe run as separate programs. Their upstream binary archive is pinned by SHA-256 `1840634b3f2ce1512d9208f1ea96084bed42cf4b80a94546ff1a8757a594e389`; the matching BtbN build-recipe revision is `63ac3265b0789ea16c7b1f8351cd2ad195a28722`. The portable app includes only ffmpeg and ffprobe from that archive. Preserve the accompanying LGPL/GPL license texts and individual dependency notices when sharing them. The source companions linked from the release contain the matching source and build materials, including the dependency cache from the same upstream build. Users retain the rights granted by those component licenses, including modification and reverse engineering where those licenses permit it.

Keep the OpenAI Whisper model license and whisper.cpp license as separate notices. Keep the Python distribution's license, Tcl/Tk license, installed package licenses and bundled library notices with the executable. PyInstaller's bootloader exception permits the generated application to use its own license; it does not replace dependency licenses.

The MIT license for Hisser's source does not replace the LGPL, Microsoft, NVIDIA or other terms applicable to bundled third-party components.
