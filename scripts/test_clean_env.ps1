Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

$vars = @(
    "JARVIS_LIVE_RESILIENCE",
    "JARVIS_CONCURRENT_TASK_RUNTIME",
    "JARVIS_SPEECH_CONTROL",
    "JARVIS_ACTION_DECISION_GATE",
    "JARVIS_TOOL_CALL_GATE",
    "JARVIS_MEMORY_DECISION_POLICY",
    "JARVIS_MEMORY_WRITE_BACKEND",
    "JARVIS_READONLY_MEMORY"
)

foreach ($var in $vars) {
    Remove-Item "Env:$var" -ErrorAction SilentlyContinue
}

$remaining = Get-ChildItem Env:JARVIS_* -ErrorAction SilentlyContinue | Sort-Object Name
if ($remaining) {
    Write-Host "[test_clean_env] Remaining JARVIS_* variables:"
    $remaining | ForEach-Object { Write-Host ("{0}={1}" -f $_.Name, $_.Value) }
} else {
    Write-Host "[test_clean_env] No remaining JARVIS_* variables."
}

& .\.venv\Scripts\python.exe -m unittest discover tests
exit $LASTEXITCODE
