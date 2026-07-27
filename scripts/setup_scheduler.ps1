# setup_scheduler.ps1
# Sets up Windows Task Scheduler tasks for the H.A.T.S systematic trading bot.

$WorkingDirectory = "d:\stocks"
$PythonPath = "python" # Assumes python is on PATH. If using a venv, point to venv/Scripts/python.exe

# 1. Register Daily Systematic Trading Cycle (Mon-Fri at 4:05 PM ET / 16:05 to align with Linux timer)
$TradingAction = New-ScheduledTaskAction -Execute $PythonPath -Argument "-m src.main --interval 1d" -WorkingDirectory $WorkingDirectory
$TradingTrigger = New-ScheduledTaskTrigger -Daily -At "4:05PM"
# Days of week filter (Mon-Fri) is best done via custom task definition or trigger adjustments
# But basic New-ScheduledTaskTrigger -Daily works daily. We can filter in the python code anyway (market hours check).

$TradingSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName "HATS-DailyCycle" -Action $TradingAction -Trigger $TradingTrigger -Settings $TradingSettings -Description "Runs H.A.T.S systematic daily trading cycle at 4:05 PM." -Force

# 2. Register Dashboard Server (At Startup)
$DashboardAction = New-ScheduledTaskAction -Execute $PythonPath -Argument "-m src.dashboard.app --port 8000" -WorkingDirectory $WorkingDirectory
$DashboardTrigger = New-ScheduledTaskTrigger -AtStartup
$DashboardSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName "HATS-DashboardServer" -Action $DashboardAction -Trigger $DashboardTrigger -Settings $DashboardSettings -Description "Runs H.A.T.S Dashboard FastAPI Server on startup." -Force

Write-Host "✅ H.A.T.S Windows tasks successfully scheduled!"
Write-Host "• HATS-DailyCycle: Runs daily at 4:05 PM."
Write-Host "• HATS-DashboardServer: Runs on system startup."
