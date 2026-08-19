# Apply idle-only conditions to EnneadTab_SchedulePublisher.
# RunOnlyIfIdle waits for system idle; StopOnIdleEnd=false so a started publish finishes.
param(
    [string]$TaskName = "EnneadTab_SchedulePublisher",
    [string]$WorkingDirectory = ""
)

$ErrorActionPreference = "Stop"

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$settings = $task.Settings
$settings.AllowDemandStart = $true
$settings.StartWhenAvailable = $true
$settings.RunOnlyIfIdle = $true
$settings.IdleSettings.IdleDuration = "PT10M"
$settings.IdleSettings.WaitTimeout = "PT2H"
$settings.IdleSettings.StopOnIdleEnd = $false
$settings.IdleSettings.RestartOnIdle = $true
$settings.ExecutionTimeLimit = "PT3H"
$settings.MultipleInstances = "IgnoreNew"

$action = $task.Actions[0]
if ($WorkingDirectory -and (Test-Path -LiteralPath $WorkingDirectory)) {
    $action.WorkingDirectory = (Resolve-Path -LiteralPath $WorkingDirectory).Path
}

Set-ScheduledTask -TaskName $TaskName -Action $action -Settings $settings | Out-Null

$verify = Get-ScheduledTask -TaskName $TaskName
Write-Host "Idle applied: RunOnlyIfIdle=$($verify.Settings.RunOnlyIfIdle) IdleDuration=$($verify.Settings.IdleSettings.IdleDuration) StopOnIdleEnd=$($verify.Settings.IdleSettings.StopOnIdleEnd)"
Write-Host "WorkingDirectory=$($verify.Actions[0].WorkingDirectory)"
