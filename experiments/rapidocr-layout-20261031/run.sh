#!/usr/bin/env bash
set -euo pipefail
lab=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd -- "$lab/../.." && pwd)
archive=${1:?Pass the directory containing historical experiment artifacts}
out=${2:-"$lab/outputs/$(date -u +%Y%m%dT%H%M%SZ)"}
case ${3:-validate} in
  validate) script=validate.py;;
  regression) script=regression.py;;
  *) echo 'Mode must be validate or regression' >&2; exit 1;;
esac
image=sha256:141ee6ffbc6d0ec0c025f9deccbf93ae832f6721ef90018de93312b6dfc36c1b
docker image inspect "$image" >/dev/null
archive=$(realpath -- "$archive")
mkdir -p -- "$out"
out=$(realpath -- "$out")
case "$out/" in "$archive/"*) echo 'Output must not overwrite historical artifacts' >&2; exit 1;; esac
docker run --rm --network none --read-only --cap-drop ALL --user "$(id -u):$(id -g)" \
  --security-opt no-new-privileges --cpus 2 --memory 4g --pids-limit 128 \
  --tmpfs /tmp:rw,size=256m --tmpfs /workspace:rw,size=768m \
  -e PYTHONDONTWRITEBYTECODE=1 -e OMP_NUM_THREADS=1 -e EXPERIMENT_IMAGE_ID="$image" \
  --mount "type=bind,source=$lab,target=/lab,readonly" \
  --mount "type=bind,source=$archive,target=/archive,readonly" \
  --mount "type=bind,source=$repo/plugins/tools,target=/repo/plugins/tools,readonly" \
  --mount "type=bind,source=$repo/experiments/rapidocr-body-20261030,target=/repo/experiments/rapidocr-body-20261030,readonly" \
  --mount "type=bind,source=$out,target=/out" \
  "$image" /opt/rapid/bin/python "/lab/$script" run
