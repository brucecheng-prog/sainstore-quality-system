$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$taskName = "SainStore Quality System Background"
$batchPath = Join-Path $scriptDir "start_windows_background.bat"

if (-not (Test-Path $batchPath)) {
    throw "Start script not found: $batchPath"
}

$whoami = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

Write-Host ""
Write-Host "Registering startup task..."
Write-Host "Task name: $taskName"
Write-Host "Run as: $whoami"
Write-Host ""
Write-Host "Notes:"
Write-Host "1. Windows will ask for the account password, not the PIN."
Write-Host "2. After registration, the app can start in the background at boot."
Write-Host "3. SYSTEM is not used because dws auth belongs to the current user."
Write-Host ""

$taskCommand = 'cmd.exe /c ""{0}""' -f $batchPath

$arguments = @(
    "/Create",
    "/TN", $taskName,
    "/SC", "ONSTART",
    "/DELAY", "0000:30",
    "/RL", "HIGHEST",
    "/F",
    "/RU", $whoami,
    "/RP", "*",
    "/TR", $taskCommand
)

Write-Host "Windows will now ask for the password of account $whoami."
Write-Host ""
& schtasks.exe @arguments

if ($LASTEXITCODE -ne 0) {
    throw "Task registration failed. Make sure you entered the Windows account password, not the PIN."
}

Write-Host ""
Write-Host "Task registered: $taskName"
Write-Host "Next commands:"
Write-Host "1. .\start_windows_background.bat"
Write-Host "2. .\check_windows_background.bat"
Write-Host "3. Reboot the mini PC and check status again"
