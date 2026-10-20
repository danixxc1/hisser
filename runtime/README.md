# Runtime inputs

This directory holds generated runtime binaries during development. They are ignored by Git and are created by `scripts/prepare_runtime.py`. Source preparation reuses an existing FFmpeg/ffprobe pair on PATH. The portable app bundles that pair and needs no system FFmpeg for daily use.

Pinned recognition runtime:

- [Official whisper.cpp CPU x64 b5454 ZIP](https://github.com/ggml-org/whisper.cpp/releases/download/b5454/whisper-bin-x64.zip)
- SHA-256: `6ba69e3482d7826214f90a6a9c84ca07782aec1e1d0c6a7c30c994fd5d816ccb`
- [Official CUDA 11.8 x64 b5454 ZIP](https://github.com/ggml-org/whisper.cpp/releases/download/b5454/whisper-bin-win-cuda-11.8.0-x64.zip)
- CUDA ZIP: 284,761,231 bytes; SHA-256 `e81c86c542be6e3d7b7245392d4e1c52ab6e5c61dbe38721754bc0ab59d4d027`.
- The CUDA ZIP is not self-contained. Setup also bundles only the required cuBLAS DLLs and license from NVIDIA's [CUDA 11.8 redistribution manifest](https://developer.download.nvidia.com/compute/cuda/redist/redistrib_11.8.0.json).
- NVIDIA cuBLAS 11.11.3.6 ZIP: 420,850,025 bytes; SHA-256 `67b0934a6359e4ee26fff823c356021589d392c4fd49ca12624f570edc08e2b9`.
- `cublas64_11.dll`: 88,668,160 bytes; SHA-256 `8ca516b96b29c2fba2344909a896bc1cd7951f6cd11fe595a8a3929c02cccbed`.
- `cublasLt64_11.dll`: 544,070,144 bytes; SHA-256 `3d06ca4e4893adb7a153ecd23a540e92817c967312b44646d8c3f91b089196e6`.

Pinned multilingual models (retain one in the portable app):

- [Pinned model revision](https://huggingface.co/ggerganov/whisper.cpp/tree/5359861c739e955e79d9a303bcbc70fb988958b1)
- Current model: `ggml-large-v3-q5_0.bin`, 1,081,140,203 bytes; SHA-256 `d75795ecff3f83b5faa89d1900604ad8c780abd5739fae406de19f23ecd98ad1`.
- Turbo candidate: `ggml-large-v3-turbo-q5_0.bin`, 574,041,195 bytes; SHA-256 `394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2`.

`--backend cuda` prepares both CPU and CUDA runtimes; it does not install a driver or GPU toolkit. An existing compatible NVIDIA driver is required for GPU use. `--model large-v3-turbo-q5_0` explicitly prepares the Turbo candidate; the default remains large-v3. Preparation writes `transcription-profile.json` beside `models`, selecting the catalog model and six CPU threads. Missing profiles preserve legacy large-v3; invalid profiles produce a retryable error.

CUDA/cuBLAS plus the original media runtime and Turbo total about 2.309 GB before Python/Tk and app files. The approved final storage ceiling is strictly **4,000,000,000 bytes**. Packaging checks the complete folder, including hidden files and verification records. Comparison copies are temporary and excluded from the final portable folder.

Generated `provenance.json` records exact URLs, hashes, installed FFmpeg version and local paths. It remains local because paths can contain account information. Official whisper/cuBLAS binaries can be unsigned; upstream SHA-256 verification and security-scan results are recorded separately. Licenses are bundled with the app. Keep generated DLLs, EXEs and model weights out of Git.
