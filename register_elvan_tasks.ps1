$workingDirectory = "C:\Users\resoa\Videos\X_Post"

$legacyTasks = @(
    "ElvanAgent_Engage_Morning",
    "ElvanAgent_Engage_Midday",
    "ElvanAgent_Engage_Evening",
    "ElvanAgent_Publish_1",
    "ElvanAgent_Publish_2",
    "ElvanAgent_Publish_3",
    "ElvanAgent_Daily_Report"
)

foreach ($taskName in $legacyTasks) {
    try {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop
    } catch {
        # Ignore missing legacy tasks.
    }
}

$buildQueueAction = New-ScheduledTaskAction `
    -Execute "python" `
    -Argument "$workingDirectory\orchestrator.py build-queue" `
    -WorkingDirectory $workingDirectory
$buildQueueTrigger = New-ScheduledTaskTrigger -Daily -At "08:00"
$buildQueueSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask `
    -TaskName "ElvanAgent_BuildQueue" `
    -Action $buildQueueAction `
    -Trigger $buildQueueTrigger `
    -Settings $buildQueueSettings `
    -Force

$redditMonitorAction = New-ScheduledTaskAction `
    -Execute "python" `
    -Argument "$workingDirectory\reddit_monitor.py" `
    -WorkingDirectory $workingDirectory
$redditMonitorTrigger = New-ScheduledTaskTrigger -Daily -At "07:50"
$redditMonitorSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask `
    -TaskName "ElvanAgent_Reddit_Monitor" `
    -Action $redditMonitorAction `
    -Trigger $redditMonitorTrigger `
    -Settings $redditMonitorSettings `
    -Force

$dailyReportAction = New-ScheduledTaskAction `
    -Execute "python" `
    -Argument "$workingDirectory\orchestrator.py daily-report" `
    -WorkingDirectory $workingDirectory
$dailyReportTrigger = New-ScheduledTaskTrigger -Daily -At "22:00"
$dailyReportSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask `
    -TaskName "ElvanAgent_DailyReport" `
    -Action $dailyReportAction `
    -Trigger $dailyReportTrigger `
    -Settings $dailyReportSettings `
    -Force

$statsReportAction = New-ScheduledTaskAction `
    -Execute "python" `
    -Argument "$workingDirectory\orchestrator.py stats-report" `
    -WorkingDirectory $workingDirectory
$statsReportTrigger = New-ScheduledTaskTrigger -Daily -At "22:05"
$statsReportSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask `
    -TaskName "ElvanAgent_StatsReport" `
    -Action $statsReportAction `
    -Trigger $statsReportTrigger `
    -Settings $statsReportSettings `
    -Force
