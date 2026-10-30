param([ValidateSet('render','run','evaluate')][string]$Action='run')
$ErrorActionPreference='Stop'
$taskLab=$PSScriptRoot
$taskRepo=Split-Path (Split-Path $taskLab -Parent) -Parent
$taskSamples=Join-Path $taskLab 'samples'
$taskPrevious=Join-Path $taskRepo 'experiments/ocr-smoke-20261019'
$taskPrior=Join-Path $taskRepo 'experiments/rapidocr-smoke-20261019'
$taskReader=Join-Path $taskRepo 'plugins/tools'
$taskImage=(docker image inspect frontier-rapidocr-expanded:20261030-5db5 --format '{{.Id}}').Trim()
if ($LASTEXITCODE -ne 0) { throw 'Experiment image unavailable' }
$taskImage | Set-Content (Join-Path $taskLab 'outputs/image-id.txt')
$taskProgram=if ($Action -eq 'render') {'/lab/render.py'} else {'/lab/experiment.py'}
docker run --rm --name frontier-rapidocr-expanded --network none --read-only --cap-drop ALL --security-opt no-new-privileges --cpus 2 --memory 4g --pids-limit 128 --tmpfs /tmp:rw,size=256m --tmpfs /workspace:rw,size=256m --mount "type=bind,source=$taskLab,target=/lab" --mount "type=bind,source=$taskSamples,target=/samples,readonly" --mount "type=bind,source=$taskPrevious,target=/previous,readonly" --mount "type=bind,source=$taskPrior,target=/prior,readonly" --mount "type=bind,source=$taskReader,target=/reference,readonly" $taskImage /opt/rapid/bin/python $taskProgram $Action
if ($LASTEXITCODE -ne 0) { throw "Experiment exited $LASTEXITCODE" }
