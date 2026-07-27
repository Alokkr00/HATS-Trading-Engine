# remove_scheduler.ps1
# Unregisters H.A.T.S tasks from Windows Task Scheduler.

try {
    Unregister-ScheduledTask -TaskName "HATS-DailyCycle" -Confirm:$false
    Write-Host "🗑️ Unregistered task: HATS-DailyCycle"
} catch {
    Write-Host "ℹ️ Task HATS-DailyCycle not found or could not be unregistered."
}

try {
    Unregister-ScheduledTask -TaskName "HATS-MorningCycle" -Confirm:$false
    Write-Host "🗑️ Unregistered task: HATS-MorningCycle"
} catch {
    Write-Host "ℹ️ Task HATS-MorningCycle not found or could not be unregistered."
}

try {
    Unregister-ScheduledTask -TaskName "HATS-DashboardServer" -Confirm:$false
    Write-Host "🗑️ Unregistered task: HATS-DashboardServer"
} catch {
    Write-Host "ℹ️ Task HATS-DashboardServer not found or could not be unregistered."
}

Write-Host "✅ H.A.T.S Windows scheduler cleanup completed."
