param(
    [int[]]$Ports = @(7860, 7863, 7870),
    [switch]$KeepWindow
)

$ErrorActionPreference = "Continue"

Write-Host "Stopping Kimodo-related ports: $($Ports -join ', ')"

$killed = New-Object System.Collections.Generic.HashSet[int]

foreach ($port in $Ports) {
    $connections = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if (-not $connections) {
        Write-Host "Port ${port}: not in use"
        continue
    }

    foreach ($connection in $connections) {
        $pidValue = [int]$connection.OwningProcess
        if ($pidValue -le 0 -or $killed.Contains($pidValue)) {
            continue
        }

        try {
            $process = Get-Process -Id $pidValue -ErrorAction Stop
            Write-Host "Stopping PID $pidValue ($($process.ProcessName)) on port $port"
            Stop-Process -Id $pidValue -Force -ErrorAction Stop
            [void]$killed.Add($pidValue)
        }
        catch {
            Write-Host "Failed to stop PID $pidValue on port ${port}: $($_.Exception.Message)"
        }
    }
}

Write-Host "Done. Stopped $($killed.Count) process(es)."

if ($KeepWindow) {
    Write-Host ""
    Write-Host "Press Enter to close..."
    [void][System.Console]::ReadLine()
}
