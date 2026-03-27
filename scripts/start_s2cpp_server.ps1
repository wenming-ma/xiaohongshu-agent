param(
    [int]$Port = 3030,
    [int]$CudaDevice = 0,
    [string]$ListenAddr = "127.0.0.1"
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path "$PSScriptRoot\.."
$s2 = Join-Path $root "submodules\s2.cpp_check"
$exe = Join-Path $s2 "build-cuda\Release\s2.exe"
$dllDir = Join-Path $s2 "build-cuda\bin\Release"
$model = Join-Path $s2 "models\s2-pro-q8_0.gguf"
$tokenizer = Join-Path $s2 "models\tokenizer.json"

foreach ($p in @($exe, $model, $tokenizer)) {
    if (-not (Test-Path -LiteralPath $p)) {
        Write-Error "Missing: $p"
        exit 1
    }
}

$env:PATH = "$dllDir;$env:PATH"

Write-Host "Starting s2.cpp server on ${ListenAddr}:${Port} (CUDA device $CudaDevice)" -ForegroundColor Cyan
Write-Host "Model : $model"
Write-Host "Press Ctrl+C to stop"
Write-Host ""

& $exe -m $model -t $tokenizer -c $CudaDevice --server -H $ListenAddr -P $Port
