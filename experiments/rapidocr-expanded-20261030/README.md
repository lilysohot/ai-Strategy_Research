# RapidOCR small expanded isolated experiment

This directory is ignored by Git and is not imported by FrontierAgent. It contains a 26-page experiment and its local results, not a production OCR adapter.

## Reproduce the recorded sample

Use the preserved `manifest.json`, `reference-frozen.json`, `reference-errata.json`, and `samples/`. The manifest records original filenames, pages and SHA256 hashes. Do not regenerate the inventory to reproduce this run: adding corpus files can change the inventory IDs. The staged 14 PDF copies must match the recorded hashes.

The sibling `ocr-smoke-20261019` experiment provides the measurement helper, current-reader baseline bundler and blank/damaged controls. The sibling `rapidocr-smoke-20261019` provides the unchanged small OCR worker and settings. These are mounted read-only. The production `plugins/tools` directory is mounted read-only. Scripts use explicit page selections to avoid the production whole-document cache; `READDOC_` variables are removed from baseline subprocess environments.

From the repository root in PowerShell:

```powershell
docker build -t frontier-rapidocr-expanded:20261030-5db5 experiments/rapidocr-expanded-20261030
python experiments/rapidocr-expanded-20261030/snapshot.py before
./experiments/rapidocr-expanded-20261030/run.ps1 render
./experiments/rapidocr-expanded-20261030/run.ps1 run
./experiments/rapidocr-expanded-20261030/run.ps1 evaluate
python experiments/rapidocr-expanded-20261030/layout_diagnostic.py
python experiments/rapidocr-expanded-20261030/posthoc_audit.py
python experiments/rapidocr-expanded-20261030/verify_sources.py
python experiments/rapidocr-expanded-20261030/snapshot.py after
python experiments/rapidocr-expanded-20261030/build_report.py
```

Existing `outputs/runs/*` are checkpoints reused by `run`, including any failure states. Archive those files before requesting a wholly fresh OCR measurement. Re-running baseline, evaluation and report steps overwrites their local experiment outputs. Preserve existing snapshots and results if retaining separate run histories.

The Dockerfile pins the base image digest and all prior Python dependencies. Model preparation explicitly initializes detection, direction classification and recognition, then verifies all three model hashes against the prior experiment. Build context excludes PDFs and results. The initial Docker Hub authentication request failed; the same public Python image family was obtained from the public ECR mirror and its actual digest pinned. Python is 3.12.16 in this image, not the previous 3.12.14. The original experiment image had been removed. `outputs/image-id.txt` records the image actually used.

Rendering and OCR use network-disabled containers with a read-only root filesystem, dropped capabilities, no-new-privileges, 2 CPU quota, 4 GiB memory cap and 90-second worker deadlines. Only experiment outputs/temp paths are written; no original corpus directory or credentials are mounted. The full experiment directory is writable for artifacts; samples are accessed via the additional `/samples` read-only mount. Original files are independently checked on the host, without rewriting them.

## Scope and measurement

- 14 documents, 26 pages: 13 scanned/image pages and 13 pages with some native text. Of the scanned pages, 10 contain scored body text; 2 financial tables and 1 bibliography/chart page are operational controls only.
- 23 body pages: 16 Chinese, 5 English, 2 bilingual; 21 newly evaluated body pages plus 2 prior regression pages. Samples are purposively selected, not a random corpus estimate.
- 26 primary fresh-process runs; 5 sentinel pages get two additional fresh-process repeats. Wall includes imports, rasterization, lazy model loading and OCR. Worker-tree RSS is sampled every 20ms and is not a whole-host memory guarantee. No performance extrapolation to production concurrency.
- The PDF renderer uses 300 DPI and a 25-megapixel budget. RapidOCR retains the prior defaults (global maximum side2000, detector minimum side736, recognition score threshold0.5) and one ONNX intra/inter thread. PDF upsampling cannot restore missing source detail.
- Source preview pages were reviewed before OCR. The frozen reference contains 48 body excerpts and 127 key checks. Source-only verification found one omitted character and two en-dash ranges in the transcription; all corrections are explicit in `reference-errata.json`. The original reference hash remains unchanged. The effective evaluated reference is written separately to `outputs/reference-effective.json`.
- Primary CER uses the entire reference against its best contiguous OCR span with semiglobal Levenshtein distance. Whitespace is ignored; punctuation and case count. It includes reading-order noise and may optimistically match a similar span elsewhere. It is not full-page character accuracy or document recall.
- The native comparison uses actual unchanged production reader `text` output, not a separate extractor. The 13 native-text pages include two whose Chinese text is missing; simply counting native characters would miss that problem.
- Predeclared experimental gates are stored in the frozen reference. A fixed excerpt is flagged missing only when its best-span CER reaches50%. A passing excerpt gate does not prove all body lines were retained: post-hoc source review found two additional garbled body lines.
- Strict key checks match normalized whitespace only, anywhere on the page; they do not verify context, every occurrence or relation to a particular company. Supplementary dash/NFKC normalization is reported separately and does not replace the strict gate.
- `layout_diagnostic.py` selects four manually inspected body-column rectangles using existing OCR boxes, then sorts within them. It changes no OCR text and reruns no inference. It is a post-hoc diagnostic, not an automatic layout algorithm, and is excluded from primary acceptance metrics.
- `posthoc_audit.py` records known garbled body lines and the high-score extra-W unit error. Low confidence can indicate trouble but high confidence is not a factual correctness guarantee. These findings are not silently folded into the frozen score.

## Checks and retained artifacts

78 baseline outputs (26 pages × auto/text/image) match between baseline and OCR-enabled environments using the same pypdf version. These checks are local reader smoke tests, not application end-to-end integration tests. Blank and damaged controls distinguish empty from error. A short startup timeout verifies worker process-group termination; no worker remains. All68 corpus originals, 14 staged copies and780 existing tracked/configuration files were verified unchanged.

`REPORT.zh-CN.md` summarizes the decision. `PAGE_REVIEW.zh-CN.md` provides page names, source preview links, raw OCR links and every scored excerpt. Raw JSON retains OCR boxes, scores, stdout/stderr, time and RSS. `summary.json`, `evaluation.json`, `layout-diagnostic.json`, `posthoc-audit.json`, `checks.json` and isolation snapshots make the conclusions auditable. No production configuration or OCR switch was enabled.
