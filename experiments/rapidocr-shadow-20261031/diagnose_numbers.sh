#!/usr/bin/env bash
set -euo pipefail
lab=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd -- "$lab/../.." && pwd)
mode=${1:?Pass baseline, trace-cls, no-cls or table-crop}
out=$(realpath -m -- "${2:?Pass a new diagnostic output directory}")
case "$out/" in "$lab/outputs/"*) ;; *) exit 2;; esac
mkdir -p -- "$out"
test ! -e "$out/$mode.json"
docker run --rm --network none --read-only --cap-drop ALL --user "$(id -u):$(id -g)" \
  --security-opt no-new-privileges --cpus 2 --memory 4g --pids-limit 128 \
  --tmpfs /tmp:rw,size=256m -e PYTHONDONTWRITEBYTECODE=1 -e OMP_NUM_THREADS=1 \
  --mount "type=bind,source=$lab,target=/lab,readonly" \
  --mount "type=bind,source=$lab/outputs/20261030T165838Z,target=/prior,readonly" \
  --mount "type=bind,source=$repo/experiments/rapidocr-smoke-20261019/config.py,target=/modelconfig/config.py,readonly" \
  --mount "type=bind,source=$out,target=/out" \
  sha256:141ee6ffbc6d0ec0c025f9deccbf93ae832f6721ef90018de93312b6dfc36c1b \
  /opt/rapid/bin/python /lab/diagnose_numbers.py "$mode" --assert-exact
