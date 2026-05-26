param()

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
