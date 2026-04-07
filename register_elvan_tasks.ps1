$tasks = @(
    @{
        Name = "ElvanAgent_Engage_Morning"
        Argument = "orchestrator.py engage"
        Time = "09:00"
    },
    @{
        Name = "ElvanAgent_Engage_Midday"
        Argument = "orchestrator.py engage"
        Time = "12:30"
    },
    @{
        Name = "ElvanAgent_Engage_Evening"
        Argument = "orchestrator.py engage"
        Time = "17:00"
    },
    @{
        Name = "ElvanAgent_Publish_1"
        Argument = "orchestrator.py publish"
        Time = "10:30"
    },
    @{
        Name = "ElvanAgent_Publish_2"
        Argument = "orchestrator.py publish"
        Time = "14:00"
    },
    @{
        Name = "ElvanAgent_Publish_3"
        Argument = "orchestrator.py publish"
        Time = "19:30"
    },
    @{
        Name = "ElvanAgent_Daily_Report"
        Argument = "orchestrator.py daily-report"
        Time = "22:00"
    }
)

$workingDirectory = "C:\Users\resoa\Videos\X_Post"

foreach ($task in $tasks) {
    $action = New-ScheduledTaskAction `
        -Execute "python" `
        -Argument "$workingDirectory\$($task.Argument)" `
        -WorkingDirectory $workingDirectory

    $trigger = New-ScheduledTaskTrigger -Daily -At $task.Time
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 1)

    Register-ScheduledTask `
        -TaskName $task.Name `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Force
}
