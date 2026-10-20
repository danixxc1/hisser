# Third-party components

Hisser's own source is licensed under the [MIT License](LICENSE). The components below retain their separate licenses. The source repository excludes executable runtime binaries, model weights and private test recordings. Downloadable app releases carry the applicable complete license texts and corresponding source materials described in [Distribution](docs/DISTRIBUTION.md).

| Component | Purpose | Upstream license/source |
| --- | --- | --- |
| whisper.cpp b5454 (source commit `d1be6fde11ac6e0407606b4e42fe72d34add8037`) | CPU and NVIDIA CUDA speech recognition | [MIT](https://github.com/ggml-org/whisper.cpp/blob/b5454/LICENSE) |
| Whisper large-v3 / large-v3-turbo, GGML Q5_0 | Selected multilingual recognition model | [OpenAI Whisper MIT](https://github.com/openai/whisper/blob/main/LICENSE), [GGML distribution](https://huggingface.co/ggerganov/whisper.cpp) |
| NVIDIA CUDA 11.8 / cuBLAS 11.11.3.6 | Optional GPU runtime libraries | [CUDA toolkit license](https://docs.nvidia.com/cuda/archive/11.8.0/eula/index.html); see bundled NVIDIA-CUDA-cuBLAS-LICENSE.txt |
| FFmpeg / ffprobe 9.0.2 | Media inspection and decoding | Release build: LGPL 2.1 or later, built from [pinned official source](https://github.com/FFmpeg/FFmpeg/tree/946fcce07b6dcd0331c8cc609192aeff5e1924f8) without optional external libraries, GPL or nonfree components. Exact source and recipe accompany the release; see [FFmpeg license information](https://ffmpeg.org/legal.html). |
| Microsoft Visual C++ / OpenMP DLLs | Native runtime dependencies | Unmodified app-local files from Visual Studio's redistributable directories on the Windows build runner, under [Microsoft redistribution terms](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files). The release provenance identifies the Visual Studio version and its matching [redistributable file list](https://learn.microsoft.com/en-us/visualstudio/releases/2026/redistribution). |
| Python / Tk | Packaged language and native UI runtime | [Python license](https://docs.python.org/3/license.html), [Tcl/Tk license](https://www.tcl.tk/software/tcltk/license.html) |
| ReportLab | PDF generation | [ReportLab BSD license](https://hg.reportlab.com/hg-public/reportlab/file/tip/LICENSE.txt) |
| Pillow | Image support | [HPND license](https://github.com/python-pillow/Pillow/blob/main/LICENSE) |
| charset-normalizer | Text encoding support | [MIT](https://github.com/jawah/charset_normalizer/blob/master/LICENSE) |
| PyInstaller | Folder packaging | [GPL with bootloader exception](https://pyinstaller.org/en/stable/license.html) |

Windows Segoe UI is read from the local Windows Fonts folder for PDF embedding; font files are not committed to the repository. PDF support is intended for Filipino names and Latin accents. Not every script supported by Whisper has been font-tested.

The NVIDIA libraries remain under NVIDIA's terms and are supplied only for Hisser's GPU processing. They are not licensed under any Hisser or FFmpeg license. Use of these components is subject to the included NVIDIA license. They are not supplied as a standalone SDK or library package. The bundle does not include a GPU driver or CUDA development toolkit.

Keep the OpenAI Whisper model license and whisper.cpp license as separate notices. Keep the Python distribution's license, Tcl/Tk license, installed package licenses and bundled library notices with the executable. PyInstaller's bootloader exception permits the generated application to use its own license; it does not replace dependency licenses.

The MIT license for Hisser's source does not replace the LGPL, Microsoft, NVIDIA or other terms applicable to bundled third-party components.
