#!/usr/bin/env bash
set -euo pipefail
cd /home/administrator/FrontierAgent
echo "$$" > .scratch/corpus-structure-restart/s5-full-matrix-live.pid
printf '\n[%s] switching to frozen-runner concurrent dispatcher (concurrency=3)\n' "$(date --iso-8601=seconds)" >> .scratch/corpus-structure-restart/s5-full-matrix-live.log
exec env PYTHONUNBUFFERED=1 .venv/bin/python .scratch/corpus-structure-restart/s5_full_model_matrix_concurrent.py --concurrency 3 >> .scratch/corpus-structure-restart/s5-full-matrix-live.log 2>&1
