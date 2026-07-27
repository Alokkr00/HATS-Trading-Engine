# H.A.T.S Cockpit Watchdog Service
$ErrorActionPreference = "Stop"
$HealthUrl = "http://127.0.0.1:8000/api/health"
$ConsecutiveFailures = 0

Write-Host "H.A.T.S Cockpit Watchdog started. Monitoring $HealthUrl..." -ForegroundColor Green

while ($true) {
    try {
        $response = Invoke-RestMethod -Uri $HealthUrl -Method Get -TimeoutSec 5
        if ($response.status -eq "HEALTHY") {
            if ($ConsecutiveFailures -gt 0) {
                Write-Host "Server recovered. Status: HEALTHY" -ForegroundColor Green
            }
            $ConsecutiveFailures = 0
        } else {
            $ConsecutiveFailures++
            Write-Host "Server returned unhealthy status: $($response.status). Failures: $ConsecutiveFailures" -ForegroundColor Yellow
        }
    } catch {
        $ConsecutiveFailures++
        Write-Host "Failed to connect to health endpoint. Failures: $ConsecutiveFailures" -ForegroundColor Red
    }

    if ($ConsecutiveFailures -ge 2) {
        Write-Host "Critical: Two consecutive health failures detected! Restarting dashboard server..." -ForegroundColor Red
        
        # Find and stop python process listening on port 8000
        try {
            $ports = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
            foreach ($conn in $ports) {
                if ($conn.OwningProcess) {
                    Write-Host "Stopping process ID $($conn.OwningProcess) on port 8000..." -ForegroundColor Yellow
                    Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
                }
            }
        } catch {
            # Ignore errors finding port connection
        }

        # Start the dashboard process back up in a new background job
        Write-Host "Launching python -m src.dashboard.app --port 8000..." -ForegroundColor Green
        Start-Process -FilePath "python" -ArgumentList "-m src.dashboard.app --port 8000" -WorkingDirectory "d:\stocks" -NoNewWindow

        # Reset failure counter and wait for startup
        $ConsecutiveFailures = 0
        Start-Sleep -Seconds 10
    }

    Start-Sleep -Seconds 15
}
