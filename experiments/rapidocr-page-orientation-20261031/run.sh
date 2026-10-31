#!/usr/bin/env bash
set -euo pipefail
lab=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd -- "$lab/../.." && pwd)
run="$lab/outputs/v1"
mkdir -- "$run/results"
docker run --rm --network none --read-only --cap-drop ALL --user "$(id -u):$(id -g)" \
 --security-opt no-new-privileges --cpus 2 --memory 4g --pids-limit 128 \
 --tmpfs /tmp:rw,size=256m -e PYTHONDONTWRITEBYTECODE=1 -e OMP_NUM_THREADS=1 \
 --mount "type=bind,source=$lab,target=/lab,readonly" \
 --mount "type=bind,source=$run/inputs,target=/inputs,readonly" \
 --mount "type=bind,source=$run/results,target=/out" \
 --mount "type=bind,source=$repo/experiments/rapidocr-orientation-20261031,target=/eval,readonly" \
 --mount "type=bind,source=$repo/experiments/rapidocr-smoke-20261019/config.py,target=/modelconfig/config.py,readonly" \
 --mount "type=bind,source=$repo/experiments/ocr-smoke-20261019/lab.py,target=/helpers/lab.py,readonly" \
 sha256:141ee6ffbc6d0ec0c025f9deccbf93ae832f6721ef90018de93312b6dfc36c1b \
 /opt/rapid/bin/python /lab/regression.py run
