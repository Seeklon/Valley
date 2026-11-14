<#
.SYNOPSIS
Starts IGNIS independently of the invoking SSH session, using local WMI.
.DESCRIPTION
No scheduled task, password, global environment change or firewall change.
The API listens only on 127.0.0.1:8765. Logs and ownership records stay in the
project runtime. -SmokeTest starts a bounded Python heartbeat instead of the API.
#>
[CmdletBinding()]
param(
    [string]$Root = 'E:/IGNIS-Valley/app',
    [string]$Runtime = 'E:/IGNIS-Valley/runtime',
    [string]$Python = 'E:/IGNIS-Valley/.venv/Scripts/python.exe',
    [string]$Fds = 'E:/IGNIS-Valley/tools/fds-6.11.1/firemodels/FDS6/bin/fds_openmp.exe',
    [string]$CodexExecutable = '',
    [ValidateRange(1, 8)][int]$Threads = 4,
    [ValidateRange(1024, 65535)][int]$Port = 8765,
    [switch]$SmokeTest,
    [ValidateRange(10, 600)][int]$SmokeSeconds = 120
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$utf8 = New-Object System.Text.UTF8Encoding($false)
$Root = [IO.Path]::GetFullPath($Root)
$Runtime = [IO.Path]::GetFullPath($Runtime)
$Python = [IO.Path]::GetFullPath($Python)
foreach ($required in @($Root, $Python)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required path does not exist: $required" }
}
if (-not $SmokeTest -and -not (Test-Path -LiteralPath $Fds)) {
    throw "FDS executable does not exist: $Fds"
}
if ([string]::IsNullOrWhiteSpace($CodexExecutable)) {
    $packages = @(Get-AppxPackage -Name 'OpenAI.Codex' -ErrorAction SilentlyContinue |
        Sort-Object -Property Version -Descending)
    foreach ($package in $packages) {
        $candidate = Join-Path $package.InstallLocation 'app/resources/codex.exe'
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $CodexExecutable = $candidate
            break
        }
    }
    if ([string]::IsNullOrWhiteSpace($CodexExecutable)) {
        $command = Get-Command codex.exe -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -ne $command -and (Test-Path -LiteralPath $command.Source -PathType Leaf)) {
            $CodexExecutable = $command.Source
        }
    }
} elseif (-not (Test-Path -LiteralPath $CodexExecutable -PathType Leaf)) {
    throw "Configured Codex executable does not exist: $CodexExecutable"
}
$kind = 'api'
if ($SmokeTest) { $kind = 'smoke' }
$serviceDirectory = Join-Path $Runtime 'service'
[IO.Directory]::CreateDirectory($serviceDirectory) | Out-Null
$statePath = Join-Path $serviceDirectory "$kind-process.json"
$lockPath = Join-Path $serviceDirectory "$kind-launcher.lock"
$launcherLock = [IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None')

try {
    if (Test-Path -LiteralPath $statePath) {
        $existing = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
        $owned = Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$existing.pid)"
        if ($null -ne $owned -and
            $owned.CreationDate.ToUniversalTime().ToString('o') -eq $existing.creation_utc -and
            $owned.ExecutablePath -ieq $existing.executable -and
            $owned.CommandLine -ceq $existing.command_line) {
            [pscustomobject]@{
                status = 'already_running'; kind = $kind; pid = $existing.pid
                url = $existing.url; log = $existing.log; state = $statePath
            } | ConvertTo-Json -Compress
            return
        }
        # Only the detached owner may archive/replace this record, under its
        # lifetime lock. A previous bootstrap may still be publishing it.
    }
    if (-not $SmokeTest) {
        $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
        if ($listeners.Count -gt 0) { throw "Port $Port is already occupied; no process was stopped." }
    }

    $token = [Guid]::NewGuid().ToString('N')
    $runDirectory = Join-Path $serviceDirectory "$kind-$token"
    [IO.Directory]::CreateDirectory($runDirectory) | Out-Null
    $logPath = Join-Path $runDirectory 'service.log'
    $readyPath = Join-Path $runDirectory 'started.json'
    $stopPath = Join-Path $runDirectory 'stop.request'
    $heartbeatPath = Join-Path $runDirectory 'heartbeat.json'
    $configuration = @{
        root = $Root; runtime = $Runtime; token = $token; kind = $kind; port = $Port
        log = $logPath; ready = $readyPath; stop = $stopPath; heartbeat = $heartbeatPath
        state = $statePath
        smoke_seconds = $SmokeSeconds
        environment = @{
            IGNIS_ROOT = $Root; IGNIS_RUNTIME = $Runtime; IGNIS_FDS = $Fds
            IGNIS_THREADS = "$Threads"; PYTHONUTF8 = '1'; PYTHONUNBUFFERED = '1'
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($CodexExecutable)) {
        $configuration.environment.IGNIS_CODEX_EXECUTABLE = $CodexExecutable
    }
    $configJson = $configuration | ConvertTo-Json -Depth 5 -Compress
    $config64 = [Convert]::ToBase64String($utf8.GetBytes($configJson))
    # Both payloads are Base64. Paths and model names are data, never shell code.
    $bootstrap = @'
import base64, json, os, sys, threading, time, traceback
from datetime import datetime, timezone
from pathlib import Path
config = json.loads(base64.b64decode('__CONFIG_BASE64__'))
os.environ.update(config['environment'])
os.chdir(config['root'])
sys.path.insert(0, str(Path(config['root']) / 'backend'))
log = open(config['log'], 'a', encoding='utf-8', buffering=1)
sys.stdout = sys.stderr = log
os.dup2(log.fileno(), 1)
os.dup2(log.fileno(), 2)
def write_json(path, value):
    target = Path(path)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    temporary.replace(target)
from ignis.windows_process import current_process_identity, retain_process_ownership
retain_process_ownership(Path(config['state']).with_name(config['kind'] + '-ownership.lock'))
identity = current_process_identity()
url = None if config['kind'] == 'smoke' else 'http://127.0.0.1:' + str(config['port'])
# Ownership is persisted by this detached process, even if SSH disappears before
# Win32_Process.Create returns. stop-ignis never has to trust a PID by itself.
previous = Path(config['state'])
if previous.exists():
    previous.replace(str(previous) + '.stale.' + config['token'] + '.json')
write_json(config['state'], {**identity, 'schema_version': 1, 'kind': config['kind'],
    'token': config['token'], 'parent_pid': os.getppid(), 'root': config['root'],
    'runtime': config['runtime'], 'log': config['log'], 'stop_file': config['stop'],
    'heartbeat': config['heartbeat'], 'url': url})
write_json(config['ready'], {'pid': os.getpid(), 'token': config['token'],
    'started_utc': datetime.now(timezone.utc).isoformat(), 'kind': config['kind']})
print('IGNIS process started', os.getpid(), config['kind'], flush=True)
exit_code = 0
try:
    stop = Path(config['stop'])
    if config['kind'] == 'smoke':
        deadline = time.monotonic() + config['smoke_seconds']
        while not stop.exists() and time.monotonic() < deadline:
            write_json(config['heartbeat'], {'pid': os.getpid(), 'token': config['token'],
                'utc': datetime.now(timezone.utc).isoformat(), 'kind': 'harmless_python_heartbeat'})
            time.sleep(0.5)
    else:
        import uvicorn
        server = uvicorn.Server(uvicorn.Config('ignis.api:create_app', factory=True,
            host='127.0.0.1', port=config['port'], workers=1, log_level='info'))
        def watch_stop():
            while not stop.exists():
                time.sleep(0.5)
            server.should_exit = True
        threading.Thread(target=watch_stop, daemon=True, name='ignis-stop-request').start()
        server.run()
except BaseException:
    exit_code = 1
    traceback.print_exc()
finally:
    write_json(str(Path(config['ready']).with_name('exited.json')),
        {'pid': os.getpid(), 'token': config['token'], 'exit_code': exit_code,
         'exited_utc': datetime.now(timezone.utc).isoformat()})
    print('IGNIS process exited', exit_code, flush=True)
sys.exit(exit_code)
'@
    $bootstrap = $bootstrap.Replace('__CONFIG_BASE64__', $config64)
    $bootstrap64 = [Convert]::ToBase64String($utf8.GetBytes($bootstrap))
    $commandLine = '"{0}" -X utf8 -u -c "import base64;exec(base64.b64decode(''{1}''))"' -f $Python, $bootstrap64
    $startup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{
        ShowWindow = [uint16]0; CreateFlags = [uint32]8 # DETACHED_PROCESS, supported by WMI
    }
    $created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = $commandLine; CurrentDirectory = $Root; ProcessStartupInformation = $startup
    }
    if ($created.ReturnValue -ne 0) { throw "WMI process creation failed: $($created.ReturnValue)" }

    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    while (-not (Test-Path -LiteralPath $readyPath) -and [DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Milliseconds 100
    }
    if (-not (Test-Path -LiteralPath $readyPath)) {
        throw "No startup record for WMI PID $($created.ProcessId). Inspect $logPath before retrying."
    }
    $ready = Get-Content -Raw -LiteralPath $readyPath | ConvertFrom-Json
    if ($ready.token -cne $token) { throw 'Startup ownership token does not match.' }
    # The venv redirector may have a different PID. Own the actual Python API
    # process, which owns the FDS Job Object, rather than its launcher wrapper.
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$ready.pid)"
    if ($null -eq $processInfo) { throw "The new process already exited. Inspect $logPath" }
    $url = "http://127.0.0.1:$Port"
    if ($SmokeTest) { $url = $null }
    $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
    if ($state.token -cne $token -or $state.pid -ne $ready.pid) {
        throw 'Detached process ownership record does not match this launch.'
    }
    [pscustomobject]@{
        status = 'started'; kind = $kind; pid = $ready.pid; launcher_pid = $created.ProcessId
        url = $url; log = $logPath; state = $statePath; heartbeat = $heartbeatPath
    } | ConvertTo-Json -Compress
} finally {
    $launcherLock.Dispose()
}
