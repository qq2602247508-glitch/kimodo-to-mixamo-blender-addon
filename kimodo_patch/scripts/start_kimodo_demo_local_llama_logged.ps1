param(
    [switch]$OpenWebUI = $true,
    [int]$WebUIPort = 7860,
    [int]$CommandPort = 7870,
    [int]$WaitSeconds = 180
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "logs"
$LogFile = Join-Path $LogDir "kimodo_demo_local_llama.log"
$StartScript = Join-Path $Root "scripts\start_kimodo_demo_local_llama.ps1"
$ChildScript = Join-Path $Root "scripts\run_kimodo_demo_logged_child.ps1"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Start-Process `
    -FilePath "powershell" `
    -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$ChildScript`" -StartScript `"$StartScript`" -LogFile `"$LogFile`"" `
    -WindowStyle Hidden

Write-Host "Started Kimodo demo. Log: $LogFile"

if ($OpenWebUI) {
    $webUrl = "http://127.0.0.1:$WebUIPort/"
    $apiUrl = "http://127.0.0.1:$CommandPort/health"
    Write-Host "Waiting for Kimodo WebUI: $webUrl"

    $webReady = $false
    for ($i = 0; $i -lt $WaitSeconds; $i++) {
        try {
            $response = Invoke-WebRequest -Uri $webUrl -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                $webReady = $true
                break
            }
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }

    if ($webReady) {
        Write-Host "Kimodo WebUI is ready. Opening browser..."
        Start-Process $webUrl
    }
    else {
        Write-Host "Kimodo WebUI did not respond within $WaitSeconds seconds. Check log: $LogFile"
    }

    try {
        $apiResponse = Invoke-WebRequest -Uri $apiUrl -UseBasicParsing -TimeoutSec 2
        Write-Host "Kimodo Bridge API is ready: $apiUrl"
    }
    catch {
        Write-Host "Kimodo Bridge API is not ready yet: $apiUrl"
    }
}
