$ErrorActionPreference = "Stop"

$taskName = "SainStore Quality System Background"

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Task removed: $taskName"
} else {
    Write-Host "Task not found: $taskName"
}
