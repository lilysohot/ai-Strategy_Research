# Standalone lab only. Existing production environments are never activated.
param(
    [string[]]$SamplePath = @(),
    [int[]]$Pages = @(1)
)
$ErrorActionPreference = 'Stop'
$taskLab = $PSScriptRoot
$taskRepo = Split-Path (Split-Path $taskLab -Parent) -Parent
$taskReference = Join-Path $taskRepo 'plugins/tools'
$taskTruth = (Get-Content (Join-Path $taskLab 'samples/truth.json') -Raw -Encoding utf8 | ConvertFrom-Json).'2'
$taskManifest = @(
    @{ id='control-native'; path='/lab/samples/control.pdf'; pages=@(1); truth=@{ '1'=$taskTruth } },
    @{ id='control-scan'; path='/lab/samples/control.pdf'; pages=@(2); truth=@{ '2'=$taskTruth } }
)
$taskDockerArgs = @(
    'run', '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
    '--security-opt', 'no-new-privileges', '--cpus', '2', '--memory', '4g',
    '--pids-limit', '128', '--tmpfs', '/tmp:rw,size=256m', '--tmpfs', '/workspace:rw,size=256m',
    '--mount', "type=bind,source=$taskLab,target=/lab",
    '--mount', "type=bind,source=$taskReference,target=/reference,readonly"
)
for ($taskIndex=0; $taskIndex -lt $SamplePath.Count; $taskIndex++) {
    $taskSource = (Resolve-Path -LiteralPath $SamplePath[$taskIndex]).Path
    if ($taskSource.Contains(',')) { throw 'For this experiment, use a PDF path without commas.' }
    $taskTarget = "/inputs/sample$taskIndex.pdf"
    $taskDockerArgs += @('--mount', "type=bind,source=$taskSource,target=$taskTarget,readonly")
    $taskManifest += @{ id="sample$taskIndex"; path=$taskTarget; pages=$Pages }
}
$taskJson = ConvertTo-Json -InputObject $taskManifest -Depth 6
[IO.File]::WriteAllText((Join-Path $taskLab 'manifest.json'), $taskJson, [Text.UTF8Encoding]::new($false))
# Image ID is recorded from the tested local image; building is a separate explicit action.
$taskImage = (Get-Content (Join-Path $taskLab 'outputs/image-id.txt') -Raw).Trim()
$taskDockerArgs += @($taskImage, '/opt/candidate/bin/python', '/lab/lab.py', 'run')
& docker @taskDockerArgs
if ($LASTEXITCODE -ne 0) { throw 'OCR experiment failed; inspect outputs.' }
python (Join-Path $taskLab 'verify_results.py')
if ($LASTEXITCODE -ne 0) { throw 'Experiment evidence checks failed.' }
