param()

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$StartScript = Join-Path $Root "scripts\start_kimodo_demo_local_llama_logged.ps1"

function Get-KimodoUrl {
    foreach ($port in 7860..7870) {
        $url = "http://127.0.0.1:$port"
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 1
            if ($response.Content -match "Kimodo|Viser|viser") {
                return $url
            }
        }
        catch {
        }
    }
    return $null
}

$Url = Get-KimodoUrl

if (-not $Url) {
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File $StartScript
}

$deadline = (Get-Date).AddMinutes(4)
do {
    $Url = Get-KimodoUrl
    if ($Url) {
        Start-Process $Url
        exit 0
    }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)

Start-Process "http://127.0.0.1:7860"
Write-Host "Kimodo WebUI is still starting. If the page does not load yet, refresh it in a moment."
