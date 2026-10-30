# Isolated OCR experiment

This directory is an experiment, ignored by Git and not loaded by FrontierAgent.
No production OCR adapter is implemented here. Do not copy its scripts into production.

## Isolation

- Dedicated Docker image and two virtual environments: baseline (pypdf only) and candidate (PyMuPDF plus experiment tools).
- OCR execution: network disabled, read-only container root, existing reader fragments mounted read-only, 2 CPU quota, 4 GiB memory limit, one page worker at a time, OpenMP limited to one thread.
- Only this experiment directory is writable; temporary working directories are container tmpfs.
- No project `.env`, credentials, project virtual environment or lockfile is mounted or modified.
- Supplied originals are copied and SHA-256 checked. Originals are never mounted into the OCR container for this run. Both copies and original hashes are checked after testing.
- `outputs/isolation-before.json` / `isolation-after.json` verify existing tracked files and local configuration; user pre-existing changes are preserved.

## Files

- `Dockerfile`: isolated dependency environment; `outputs/image-id.txt` identifies the immutable tested local image.
- `lab.py`: standalone page worker, original reader bundle comparison, three fresh-worker repeats, fault probes.
- `manifest.json`: synthetic control run. `real-manifest.json`: the two supplied PDFs, one page each.
- `manual-checks.json`: excerpts and key tokens transcribed visually before inspecting real OCR output.
- `evaluate_real.py`: excerpt-only CER and exact key-token checks; no full-document accuracy claim.
- `outputs/requirements-resolved.txt`, `debian-packages.tsv`, `environment.json`: actual versions, language hashes and resource limits.
- `outputs/initial-missing-poppler-data/`: retained initial evidence of the incomplete CJK rendering environment, not used for the final engine comparison.
- `outputs/real-samples/`: measured real PDF outputs and checks.

`run.ps1` reruns controls and optional supplied pages using the saved local image ID. It overwrites the current default-run results; archive those before a new run. Example from this directory:

```powershell
.\run.ps1
# Optional separate PDF files, readonly mounts; pages are 1-based:
.\run.ps1 -SamplePath 'C:\Documents\sample.pdf' -Pages 1
```

The recorded real run uses `OCR_LAB_RUN=real-samples` and `real-manifest.json`; it retains the control run in the parent output directory.
Build-time network is used only to fetch dependencies. Sample recognition has no network access.

The Dockerfile initially resolves dependencies; exact tested versions are captured in the output lock listing and the local image ID. A future fresh build can change apt dependencies: use the recorded image for exact reruns.

## Metric limits

Wall time includes worker startup, PDF loading, rendering and OCR. Memory is the peak sum of process-tree RSS sampled at 20 ms, not an exact allocator peak or the entire container's resident memory. Shared pages can be double-counted. Three repeated launches are insufficient for P95 or throughput claims; OS file caches remain warm between launches.

The two engines use the same DPI (300), language order (`chi_sim+eng`) and traineddata files. Their renderers and embedded/system Tesseract builds can differ. Original-source pixel quality is unchanged by upsampling.

Only selected visually transcribed excerpts have reference text. CER for them does not measure whole-document completeness or watermark contamination. Key-token hits do not prove correctness of nearby context or all financial figures. Native control pages forced through OCR are diagnostic only: production should continue extracting their existing text layer.

Tests establish local experimental isolation and the exercised reader output behavior, not end-to-end certification of the full agent, remote OCR, vision, every sandbox or future integration.
