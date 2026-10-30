param([ValidateSet('prepare','run','regression')][string]$Action='run')
$ErrorActionPreference='Stop'
$taskLab=$PSScriptRoot
$taskRepo=Split-Path (Split-Path $taskLab -Parent) -Parent
$taskImage=(docker image inspect frontier-rapidocr-poppler:20261030-5db5 --format '{{.Id}}').Trim()
if ($LASTEXITCODE -ne 0) {throw 'Build the isolated Poppler image first'}
$taskImage | Set-Content (Join-Path $taskLab 'outputs/image-id.txt')
$taskArgs=@('run','--rm','--name','frontier-rapidocr-poppler','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--cpus','2','--memory','4g','--pids-limit','128','--tmpfs','/tmp:rw,size=256m','--tmpfs','/workspace:rw,size=768m')
$taskMounts=@{
 '/lab'=$taskLab;
 '/samples'=(Join-Path $taskLab 'samples');
 '/body'=(Join-Path $taskRepo 'experiments/rapidocr-body-20261030');
 '/expanded'=(Join-Path $taskRepo 'experiments/rapidocr-expanded-20261030');
 '/prior'=(Join-Path $taskRepo 'experiments/rapidocr-smoke-20261019');
 '/previous'=(Join-Path $taskRepo 'experiments/ocr-smoke-20261019');
 '/reference'=(Join-Path $taskRepo 'plugins/tools')
}
foreach ($taskEntry in $taskMounts.GetEnumerator()) { $taskArgs+=@('--mount',"type=bind,source=$($taskEntry.Value),target=$($taskEntry.Key),readonly") }
$taskOut=Join-Path $taskLab 'outputs'
$taskArgs+=@('--mount',"type=bind,source=$taskOut,target=/lab/outputs",$taskImage,'/opt/rapid/bin/python','/lab/experiment.py',$Action)
& docker @taskArgs
if ($LASTEXITCODE -ne 0) {throw "Experiment exited $LASTEXITCODE"}
