# Frozen unseen-page OCR acceptance

Four real reports, one image-heavy page each. See [the report](REPORT.zh-CN.md) and [compact evidence](evidence.json). This concludes routine model/threshold experiments for the bounded, manually reviewed image-text scope. It does not enable production ingestion.

The harness reuses `../rapidocr-page-orientation-20261031/regression.py worker` unchanged. It runs existing reader auto/text/image baselines before and after, and preserves the previous body-component route independently. No model weights or source reports are committed.

The existing run is immutable: `prepare.py`, `run.sh`, and `finalize.py` create their result/manifest files exclusively and refuse overwrites. To reproduce, use a fresh checkout/work directory and stage copies using the filenames and SHA-256 values in `evidence.json` under `outputs/frozen/inputs/`. Create `selection.json` with `manifest.documents` from the evidence. Render selected PDF pages at 140 DPI as `{id}-p{page}.png` for preview (actual inference renders at 300 DPI). `prepare.py` assumes those copies exist; it does not locate or ingest reports.

From the repository root, in Linux/WSL:

```bash
.venv/bin/python experiments/rapidocr-holdout-20261031/prepare.py
bash experiments/rapidocr-holdout-20261031/run.sh
```

The existing Docker image and OCR model/config dependencies must be available. No image pulling, model replacement or dependency installation is performed by the scripts. While the container is running, record a restricted Docker inspect snapshot to `outputs/frozen/results/runtime.json` with `image_id`, `network_mode`, `readonly_rootfs`, `memory_bytes`, `nano_cpus`, `cap_drop`, `security_opt`, and `mounts` (`destination`, `rw` only).

Then run `finalize.py` under WSL. It also verifies original source hashes and the prior inventory/manifests at the local paths documented in its source; those uncommitted dependencies must be prepared before replay. It generates `review.html` and a pending `review.json`, and checks the frozen source hashes. Do not change algorithms after freezing and then silently reuse the manifest.

Checks use source-region whitespace-normalized exact or substring matching. Unknown orientation is never promoted using annotations: its 0° candidate is only a manual reference. Full raw OCR is ignored by Git; compact evidence contains only selected checks and metadata. Opening the review page does not approve it. No server, deployment, database, scheduler or production configuration is modified by this harness.
