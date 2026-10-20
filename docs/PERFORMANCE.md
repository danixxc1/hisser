# Local performance measurements

Measured on 20–21 October 2026 (Asia/Manila), on Windows 11 with an RTX 3050 Laptop GPU (4 GB VRAM), approximately 16 GB system RAM and 12 logical CPU threads. These are short-sample measurements from one laptop, not full-film speed or accuracy guarantees.

## Method

The comparison used the pinned whisper.cpp b5454 CPU and CUDA 11.8 builds, verified multilingual GGML Q5 large-v3 and large-v3-turbo models, and the existing NVIDIA driver. Each configuration ran serially, in a separate hidden process at below-normal priority. Each timing includes a fresh CLI/model start. No driver or toolkit was installed.

All inputs were 16 kHz mono PCM16 WAV. Recognition used one processor, six threads after tuning, beam size five, best-of five, original-language transcription, and ordinary temperature/no-speech defaults. CPU runs explicitly disabled GPU. No VAD, aggressive filtering, translation or reduced-quality decoding was introduced.

The English fixture contains 14.032 seconds of synthetic known speech. Three 30-second excerpts from a user-provided Filipino film were taken at 05:00, 46:40 and 85:00. The full source is 1:33:38.231. Media, recognized words, file paths and raw reports remain local under ignored `qa/`.

A replacement video produced byte-identical decoded PCM excerpts, verified by SHA-256. Its source hash was checked before and after preparation and comparison and remained unchanged. Its comparison reports explicitly link the previous measurements for identical audio; recognition was not rerun or presented as a new measurement.

## CPU thread selection

Each setting used the same synthetic English recording and large-v3 model, with a fresh CLI/model start.

| CPU threads | Wall time |
|---:|---:|
| 2 | 60.949 s |
| 4 | 41.728 s |
| 6 | 31.378 s |
| 8 | 29.911 s |

Six threads is the chosen setting: it is 4.90% slower than the fastest result and is the fewest threads within the specified 5% margin. The known English wording matched across these runs. This is a single pass, not a universal optimal-thread claim.

## CPU and GPU comparison

Wall time includes startup and model loading. The English column is a fresh matrix run, separate from the thread sweep above. Film columns are the same three audio excerpts for every configuration.

| Configuration | English 14.032 s | Film 05:00 | Film 46:40 | Film 85:00 | Film median |
|---|---:|---:|---:|---:|---:|
| large-v3 CPU | 32.806 s | 53.644 s | 93.948 s | 110.312 s | 93.948 s |
| large-v3 CUDA | 8.799 s | 4.725 s | 10.357 s | 5.970 s | 5.970 s |
| Turbo CPU | 43.054 s | 74.733 s | 46.635 s | 41.507 s | 46.635 s |
| Turbo CUDA | 2.147 s | 3.282 s | 3.049 s | 3.042 s | 3.049 s |

On these three clips, the unchanged large-v3 model with CUDA had a median wall time 15.7 times shorter than large-v3 CPU. Turbo CUDA was faster again, but its accuracy is not approved. CPU improvements varied by excerpt: Turbo CPU was slower on the English fixture and first film clip, and faster on the other two clips. Model chunk/timestamp decisions, system load, available RAM, thermals and GPU startup can affect results.

| Configuration | English startup to processing | Film startup range | Peak process RSS | Peak whole-GPU memory |
|---|---:|---:|---:|---:|
| large-v3 CPU | 1.396 s | 1.337–2.837 s | 2.109 GB | — |
| large-v3 CUDA | 7.047 s | 1.949–2.792 s | 0.389 GB | 2,134 MiB |
| Turbo CPU | 1.915 s | 0.990–1.535 s | 0.867 GB | — |
| Turbo CUDA | 1.190 s | 1.232–1.653 s | 0.389 GB | 950 MiB |

The first large-v3 CUDA English run also initialized the GPU; later processes started with the driver already awake. Every CUDA run logged the CUDA0 backend, produced timed JSON, and exited successfully. No GPU memory failure occurred on these short samples. Whole-GPU memory was sampled approximately once per second, includes other apps, and is not an exact per-process VRAM measurement. Process RSS is sampled working memory, not a full-film memory requirement or committed-memory limit. GB uses decimal bytes; MiB uses 1,048,576 bytes.

## Accuracy and acceptance limits

The synthetic English expected phrase was recognized in all four configurations. Film accuracy remains pending human listening review, including names, missing dialogue and changes in meaning. Agreement between models is not an accuracy score. CPU and GPU decoding can produce different words even with the same model. No word-error rate is claimed, and Turbo must not replace large-v3 until the user approves its wording.

The local comparison page presents each 30-second recording beside large-v3/Turbo GPU transcripts, with CPU references available underneath. The replacement video's source and prepared clip hashes were verified. These excerpts do not establish whole-film timing, continuous long-recording memory use, or late-speech coverage; the separate controlled acceptance fixture establishes speech after minute 30. See [testing instructions](TESTING.md).

## Selected portable configuration

The user selected **large-v3 Q5 with NVIDIA GPU acceleration**, retaining the existing model. Automatic is the default processing choice; CPU remains available with the measured six-thread setting. Turbo was benchmarked but was not promoted. This preserves the model choice while providing the measured GPU speed improvement; it does not establish that every GPU transcript will match CPU wording.

The deployed portable folder contains one model and occupies approximately **2.862 GB** (decimal), below the revised **4,000,000,000-byte** ceiling. PyInstaller's identical extra root copies of the two cuBLAS DLLs were removed after hash comparison with the retained CUDA files, saving 632,738,304 bytes. The complete runtime remains beside the application. No driver, toolkit or global Python package was installed.

Both models passed controlled GPU checks for synthetic English, automatic language detection, cancellation/retry, missing or damaged inputs, Unicode paths, source preservation and recognized speech after minute 30. The long source is 30:38.523 with exact silence followed by speech at 30:30; it verifies full scanning and original timestamps rather than continuous long-dialogue performance.

An explicitly injected GPU initialization failure triggered exactly one real six-thread CPU retry (32.433 seconds). Cancelling at the fallback event prevented CPU launch. No actual GPU memory failure occurred during the measurements. All five exports from the actual CPU result preserved canonical text/timing; Unicode PDF text and rendered layout passed. Model/backend metadata and the schema-version-1 timed transcript were retained.

The source suite passed 74 tests and 30 subtests. Runtime/model hashes were verified, and targeted Windows Security scans of the runtime and candidate EXE found no threats. Raw acceptance reports and comparison media remain local and excluded from Git.
