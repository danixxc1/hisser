# Third-party components

Hisser's source repository does not include model weights or executable runtime binaries. Setup downloads or copies the following components, verifies their provenance, and bundles their notices with the portable app.

| Component | Purpose | Upstream license/source |
| --- | --- | --- |
| whisper.cpp v1.9.5 / b5454 | CPU and NVIDIA CUDA speech recognition | [MIT](https://github.com/ggml-org/whisper.cpp/blob/b5454/LICENSE) |
| Whisper large-v3 / large-v3-turbo, GGML Q5_0 | Selected multilingual recognition model | [OpenAI Whisper MIT](https://github.com/openai/whisper/blob/main/LICENSE), [GGML distribution](https://huggingface.co/ggerganov/whisper.cpp) |
| NVIDIA CUDA 11.8 / cuBLAS 11.11.3.6 | Optional GPU runtime libraries | [CUDA toolkit license](https://docs.nvidia.com/cuda/archive/11.8.0/eula/index.html); see bundled NVIDIA-CUDA-cuBLAS-LICENSE.txt |
| FFmpeg / ffprobe | Media inspection and decoding | The verified Gyan full build is GPLv3; see bundled build configuration and [FFmpeg license](https://ffmpeg.org/legal.html) |
| Microsoft Visual C++ / OpenMP DLLs | whisper.cpp dependencies | Microsoft's applicable runtime terms; copied from the existing signed Windows installation for this personal app |
| Python / Tk | Packaged language and native UI runtime | [Python license](https://docs.python.org/3/license.html), [Tcl/Tk license](https://www.tcl.tk/software/tcltk/license.html) |
| ReportLab | PDF generation | [ReportLab BSD license](https://hg.reportlab.com/hg-public/reportlab/file/tip/LICENSE.txt) |
| Pillow | Image support | [HPND license](https://github.com/python-pillow/Pillow/blob/main/LICENSE) |
| PyInstaller | Folder packaging | [GPL with bootloader exception](https://pyinstaller.org/en/stable/license.html) |

Windows Segoe UI is read from the local Windows Fonts folder for PDF embedding; font files are not committed to the repository. PDF support is intended for Filipino names and Latin accents. Not every script supported by Whisper has been font-tested.

For redistribution to other people, review the bundled runtime licenses and Microsoft's runtime redistribution terms. The supplied packaging workflow is for personal Windows use; it does not grant rights beyond upstream licenses. No project-wide open-source license has been selected for Hisser's own source.
