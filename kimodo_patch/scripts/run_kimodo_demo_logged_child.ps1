param(
    [Parameter(Mandatory = $true)]
    [string]$StartScript,

    [Parameter(Mandatory = $true)]
    [string]$LogFile
)

$ErrorActionPreference = "Stop"

$LogDir = Split-Path -Parent $LogFile
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

"[$(Get-Date -Format o)] Starting Kimodo demo: $StartScript" | Out-File -FilePath $LogFile -Encoding utf8
try {
    & $StartScript *>&1 | Tee-Object -FilePath $LogFile -Append
}
catch {
    "[$(Get-Date -Format o)] ERROR: $($_.Exception.Message)" | Tee-Object -FilePath $LogFile -Append
    "[$(Get-Date -Format o)] ERROR DETAILS:" | Tee-Object -FilePath $LogFile -Append
    ($_ | Format-List * -Force | Out-String) | Tee-Object -FilePath $LogFile -Append
    if ($_.ScriptStackTrace) {
        $_.ScriptStackTrace | Tee-Object -FilePath $LogFile -Append
    }
    throw
}
