param()

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$KimodoDir = Join-Path $Root "kimodo-src"
$Demo = Join-Path $KimodoDir ".venv310\Scripts\kimodo_demo.exe"
$HfCache = Join-Path $Root "models\hf-cache"
$TextEncodersDir = Join-Path $Root "models\text-encoders-real"

if (-not (Test-Path $Demo)) {
    throw "kimodo_demo.exe was not found. Install demo dependencies first."
}

New-Item -ItemType Directory -Force -Path $HfCache | Out-Null

$env:PYTORCH_CUDA_ALLOC_CONF = "expandable_segments:True"
$env:TEXT_ENCODERS_DIR = $TextEncodersDir
$env:TEXT_ENCODER = "llm2vec"
$env:TEXT_ENCODER_MODE = "local"
$env:TEXT_ENCODER_DEVICE = "cpu"
$env:KIMODO_DISABLE_POSTPROCESSING = "1"
$env:HF_HOME = $HfCache
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:npm_config_cache = Join-Path $Root ".npm-cache"
Remove-Item Env:\HF_HUB_ENABLE_HF_TRANSFER -ErrorAction SilentlyContinue

Push-Location $KimodoDir
try {
    $ErrorActionPreference = "Continue"
    & $Demo
}
finally {
    Pop-Location
}
