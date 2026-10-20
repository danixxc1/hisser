# Runtime inputs

This directory holds generated CPU runtime binaries during development. They are ignored by Git and are created by `scripts/prepare_runtime.py`. Source preparation requires existing FFmpeg/ffprobe on PATH; no GPU toolkit is installed.

Pinned recognition runtime:

- [Official whisper.cpp CPU x64 b5454 ZIP](https://github.com/ggml-org/whisper.cpp/releases/download/b5454/whisper-bin-x64.zip)
- SHA-256: `6ba69e3482d7826214f90a6a9c84ca07782aec1e1d0c6a7c30c994fd5d816ccb`
- Model: `ggml-large-v3-q5_0.bin`, multilingual, 1,081,140,203 bytes.
- [Pinned model revision](https://huggingface.co/ggerganov/whisper.cpp/tree/5359861c739e955e79d9a303bcbc70fb988958b1)
- Model SHA-256: `d75795ecff3f83b5faa89d1900604ad8c780abd5739fae406de19f23ecd98ad1`

Generated `provenance.json` records exact URLs, hashes, installed FFmpeg version and local paths. It remains local because paths can contain account information. Licenses are bundled with the app. Keep generated DLLs, EXEs and model weights out of Git.
