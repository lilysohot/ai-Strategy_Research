#!/usr/bin/env bash
set -euo pipefail
lab=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd -- "$lab/../.." && pwd)
run=$(realpath -- "${1:?Pass the staged run directory}")
case "$run/" in "$lab/outputs/"*) ;; *) echo 'Run must be inside this experiment outputs' >&2; exit 1;; esac
test -f "$run/inputs/manifest.json"
image=sha256:141ee6ffbc6d0ec0c025f9deccbf93ae832f6721ef90018de93312b6dfc36c1b
docker image inspect "$image" >/dev/null
# Refuse to overwrite a completed/partial run or a human's review decisions.
mkdir -- "$run/results"
docker run --rm --network none --read-only --cap-drop ALL --user "$(id -u):$(id -g)" \
  --security-opt no-new-privileges --cpus 2 --memory 4g --pids-limit 128 \
  --tmpfs /tmp:rw,size=256m --tmpfs /workspace:rw,size=768m \
  -e PYTHONDONTWRITEBYTECODE=1 -e OMP_NUM_THREADS=1 -e EXPERIMENT_IMAGE_ID="$image" \
  --mount "type=bind,source=$lab,target=/lab,readonly" \
  --mount "type=bind,source=$run/inputs,target=/inputs,readonly" \
  --mount "type=bind,source=$run/results,target=/out" \
  --mount "type=bind,source=$repo/plugins/tools,target=/reference,readonly" \
  --mount "type=bind,source=$repo/experiments/rapidocr-body-20261030,target=/body,readonly" \
  --mount "type=bind,source=$repo/experiments/rapidocr-smoke-20261019/config.py,target=/modelconfig/config.py,readonly" \
  --mount "type=bind,source=$repo/experiments/ocr-smoke-20261019/lab.py,target=/helpers/lab.py,readonly" \
  "$image" /opt/rapid/bin/python /lab/trial.py run
python3 "$lab/stage.py" --verify "$run"
