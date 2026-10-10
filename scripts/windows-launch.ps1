# Launch only a new, disposable Chrome through the logged-in desktop session.
[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 9222,
    [string]$ProfileDir = (Join-Path $env:TEMP ("cdpidletabs-profile-" + [guid]::NewGuid())),
    [string]$TaskName = ("cdpidletabs-temp-" + [guid]::NewGuid()),
    [string]$ChromeExe = "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
)

$ErrorActionPreference = 'Stop'
$ProfileDir = [IO.Path]::GetFullPath($ProfileDir)
if (-not (Test-Path -LiteralPath $ChromeExe -PathType Leaf)) {
    throw 'Chrome executable not found; supply -ChromeExe with its installed path.'
}
if (Test-Path -LiteralPath $ProfileDir) {
    throw 'ProfileDir already exists; choose a new disposable directory.'
}
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    throw 'TaskName already exists; choose a new task name.'
}
$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
try { $listener.Start() } finally { $listener.Stop() }

# Print recovery values before creating anything, including if startup fails.
Write-Host "Task: $TaskName"
Write-Host "Disposable profile: $ProfileDir"
New-Item -ItemType Directory -Path $ProfileDir | Out-Null
$currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$arguments = "--no-first-run --remote-debugging-port=$Port --remote-debugging-address=127.0.0.1 --user-data-dir=`"$ProfileDir`""
$action = New-ScheduledTaskAction -Execute $ChromeExe -Argument $arguments
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
$registration = @{ TaskName = $TaskName; Action = $action; Principal = $principal }
Register-ScheduledTask @registration | Out-Null
Start-ScheduledTask -TaskName $TaskName
$version = $null
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    try {
        $version = Invoke-RestMethod "http://127.0.0.1:$Port/json/version"
        break
    } catch { Start-Sleep -Milliseconds 500 }
}
if (-not $version) {
    throw "Chrome did not expose port $Port; use the README cleanup with the printed task/profile. The user must be logged into the desktop."
}
[pscustomobject]@{ TaskName = $TaskName; ProfileDir = $ProfileDir; Port = $Port; Version = $version }
