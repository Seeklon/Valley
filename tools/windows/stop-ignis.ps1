<#
.SYNOPSIS
Requests an orderly shutdown of the process recorded by start-ignis.ps1.
.DESCRIPTION
Validates PID, creation time, executable and exact command line. Never stops a
port occupant, unrelated Python process or process whose PID has been reused.
-Force is explicit and is used only if the owned process ignores the stop file.
#>
[CmdletBinding()]
param(
    [string]$Runtime = 'E:/IGNIS-Valley/runtime',
    [switch]$SmokeTest,
    [ValidateRange(1, 120)][int]$WaitSeconds = 20,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Runtime = [IO.Path]::GetFullPath($Runtime)
$kind = 'api'
if ($SmokeTest) { $kind = 'smoke' }
$serviceDirectory = Join-Path $Runtime 'service'
$statePath = Join-Path $serviceDirectory "$kind-process.json"
if (-not (Test-Path -LiteralPath $statePath)) {
    [pscustomobject]@{ status = 'not_running'; kind = $kind } | ConvertTo-Json -Compress
    return
}
$launcherLock = [IO.File]::Open((Join-Path $serviceDirectory "$kind-launcher.lock"), 'OpenOrCreate', 'ReadWrite', 'None')
try {
    $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
    if ($state.kind -cne $kind) { throw 'Process record kind does not match.' }
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$state.pid)"
    if ($null -eq $processInfo) {
        [pscustomobject]@{ status = 'already_stopped'; kind = $kind; pid = $state.pid } | ConvertTo-Json -Compress
        return
    }
    if ($processInfo.CreationDate.ToUniversalTime().ToString('o') -ne $state.creation_utc -or
        $processInfo.ExecutablePath -ine $state.executable -or
        $processInfo.CommandLine -cne $state.command_line) {
        throw 'Process identity changed. No process was stopped.'
    }
    $ownedProcess = Get-Process -Id ([int]$state.pid)
    # Holding the native process handle prevents a PID-reuse race during stop.
    $null = $ownedProcess.Handle
    try {
        $recordedStart = [DateTime]::Parse($state.creation_utc).ToUniversalTime()
        if ([Math]::Abs(($ownedProcess.StartTime.ToUniversalTime() - $recordedStart).TotalMilliseconds) -gt 1) {
            throw 'Process start time changed. No process was stopped.'
        }
        [IO.File]::WriteAllText($state.stop_file, $state.token, (New-Object System.Text.UTF8Encoding($false)))
        $stopped = $ownedProcess.WaitForExit($WaitSeconds * 1000)
        $forced = $false
        if (-not $stopped -and $Force) {
            $ownedProcess.Kill()
            $stopped = $ownedProcess.WaitForExit(10000)
            $forced = $true
        }
        if (-not $stopped) {
            throw "Owned process $($state.pid) is still shutting down. Inspect $($state.log)."
        }
        [pscustomobject]@{
            status = 'stopped'; kind = $kind; pid = $state.pid; forced = $forced; log = $state.log
        } | ConvertTo-Json -Compress
    } finally {
        $ownedProcess.Dispose()
    }
} finally {
    $launcherLock.Dispose()
}
