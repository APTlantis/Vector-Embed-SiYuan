param(
    [ValidateSet('refresh', 'inventory', 'embed', 'status', 'search')]
    [string]$Command = 'status',
    [string]$Query = '',
    [string]$Project = ''
)
$ErrorActionPreference = 'Stop'
$runtime = 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $runtime)) { throw 'Python runtime not found. Update run.ps1 and the SiYuan MCP command to a Python installation with numpy.' }
if ($Command -eq 'refresh') {
    & $runtime "$PSScriptRoot\pipeline.py" inventory
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $runtime "$PSScriptRoot\pipeline.py" embed
} elseif ($Command -eq 'search') {
    $searchArgs = @("$PSScriptRoot\pipeline.py", 'search', $Query)
    if ($Project) { $searchArgs += @('--project', $Project) }
    & $runtime @searchArgs
} else {
    & $runtime "$PSScriptRoot\pipeline.py" $Command
}
exit $LASTEXITCODE
