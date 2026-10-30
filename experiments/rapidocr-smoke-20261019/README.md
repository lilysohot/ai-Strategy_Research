# RapidOCR CPU small-sample experiment

Independent ignored experiment. No production import, dependency, configuration, cache, or endpoint changes.

## Reproduction

Requires the existing `frontier-ocr-smoke:20261019-5db5` image and the sibling `../ocr-smoke-20261019` experiment. The latter supplies read-only PDF copies, manual references and the unchanged measurement/baseline helper.

From repository root in PowerShell:

```powershell
python experiments/rapidocr-smoke-20261019/snapshot.py before
docker build -t frontier-rapidocr-deps:20261019-5db5 experiments/rapidocr-smoke-20261019
docker build -f experiments/rapidocr-smoke-20261019/Dockerfile.models -t frontier-rapidocr-smoke:20261019-5db5 experiments/rapidocr-smoke-20261019
./experiments/rapidocr-smoke-20261019/run.ps1
./experiments/rapidocr-smoke-20261019/run.ps1 evaluate
python experiments/rapidocr-smoke-20261019/snapshot.py after
```

Builds have network access but `.dockerignore` permits only build scripts/configuration, excluding PDFs and results. The second build explicitly initializes all three lazy stages (detection, direction classification, recognition). Runtime has no network, a read-only root filesystem, no added capabilities, a 2-CPU/4-GiB limit, read-only previous experiment and reader code mounts, and writable experiment outputs/temp directories only. Source originals are not mounted.

`outputs/image-id.txt` identifies the actual immutable image used; `requirements-resolved.txt` records all installed Python dependencies and `environment.json` records model sizes and SHA256 hashes. Build scripts pin direct dependencies, but the actual recorded image is the exact reproduction artifact; rebuilding may resolve different transitive dependencies.

## Metrics

Both full-page images are rasterized at 300 DPI. RapidOCR then uses its default preprocessing (global max side 2000; detector minimum side 736). This is a pipeline comparison, not a claim of identical pixels at the recognition model input versus Tesseract. Both new configurations use identical preprocessing and one intra/inter ONNX thread. Small/medium switches both detector and recognizer; classification stays the same v4 mobile model. No GPU or vision language model is used.

Successful sample/model combinations run three times in fresh processes. A failure or 90-second timeout stops repetitions for that combination. Completed per-run JSON files are reused on resume; remove/archive experiment run outputs explicitly to request a completely fresh run. The first missing-model attempt was archived; the interrupted second medium repetition has no result and is excluded. Wall time includes imports, rasterization, lazy model loading and OCR. Peak RSS is sampled over the worker process tree every 20ms, not an OS-guaranteed maximum or complete container footprint. Historical Tesseract timings use the same CPU/memory caps but were not rerun concurrently. Do not infer production throughput or minimum hardware from this test.

`test_ocr.py evaluate` reuses prior manual references and edit-distance algorithm. Whitespace is ignored; punctuation/case differences count. Selected-excerpt CER is not full-document accuracy. Body-only results remove user1's highlighted subtitle and user2's title; body key checks exclude the stock quote +4.80%. Token presence anywhere is weaker than correct contextual extraction. Raw line boxes and model scores are retained; scores are not measured accuracy. Default recognition score cutoff 0.5 can still drop uncertain lines.

The timeout probe tests forced worker termination at startup; it does not claim a timeout during neural inference. Blank and damaged fixtures check empty/error distinction. Six existing reader outputs (two samples x auto/text/image) are compared across baseline and OCR-enabled Python environments using identical pypdf versions. This is a reader smoke test, not full end-to-end application certification.

`outputs/initial-missing-models` preserves the aborted first attempt: blank-image warmup had fetched only detection models, so network-disabled runtime correctly blocked a lazy classification download. No PDF was uploaded. The complete offline run occurs after fixing prefetch.

All outputs are local experiment artifacts. Re-running replaces experiment result files; archive them first if retaining multiple runs.
