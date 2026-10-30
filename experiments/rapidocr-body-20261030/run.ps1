param([ValidateSet('prepare','run')][string]$Action='run')
$ErrorActionPreference='Stop'
$taskLab=$PSScriptRoot
$taskRepo=Split-Path (Split-Path $taskLab -Parent) -Parent
$taskExpanded=Join-Path $taskRepo 'experiments/rapidocr-expanded-20261030'
$taskSamples=Join-Path $taskExpanded 'samples'
$taskPrevious=Join-Path $taskRepo 'experiments/ocr-smoke-20261019'
$taskPrior=Join-Path $taskRepo 'experiments/rapidocr-smoke-20261019'
$taskReader=Join-Path $taskRepo 'plugins/tools'
$taskOut=Join-Path $taskLab 'outputs'
$taskImage=(docker image inspect frontier-rapidocr-expanded:20261030-5db5 --format '{{.Id}}').Trim()
if ($LASTEXITCODE -ne 0) { throw 'Experiment image unavailable' }
if ($taskImage -ne 'sha256:7b9dce41dbd71a8a1b5a5e1b269075004def90965f02468223b203df7f3f8880') { throw 'Unexpected experiment image' }
$taskImage | Set-Content (Join-Path $taskOut 'image-id.txt')
docker run --rm --name frontier-rapidocr-body --network none --read-only --cap-drop ALL --security-opt no-new-privileges --cpus 2 --memory 4g --pids-limit 128 --tmpfs /tmp:rw,size=256m --tmpfs /workspace:rw,size=256m --mount "type=bind,source=$taskLab,target=/lab,readonly" --mount "type=bind,source=$taskOut,target=/lab/outputs" --mount "type=bind,source=$taskExpanded,target=/expanded,readonly" --mount "type=bind,source=$taskSamples,target=/samples,readonly" --mount "type=bind,source=$taskPrevious,target=/previous,readonly" --mount "type=bind,source=$taskPrior,target=/prior,readonly" --mount "type=bind,source=$taskReader,target=/reference,readonly" $taskImage /opt/rapid/bin/python /lab/experiment.py $Action
if ($LASTEXITCODE -ne 0) { throw "Experiment exited $LASTEXITCODE" }
