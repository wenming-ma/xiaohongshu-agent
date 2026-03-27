[CmdletBinding()]
param(
    [string]$VenvPath = ".venv-audio",
    [string]$PythonVersion = "3.11",
    [switch]$Recreate = $false,
    [switch]$CpuOnly = $false
)

$ErrorActionPreference = "Stop"

$projectRoot = Resolve-Path "$PSScriptRoot\.."
$venvFullPath = Join-Path $projectRoot $VenvPath
$requirementsFile = Join-Path $projectRoot "requirements\audio-venv.txt"

if (-not (Test-Path -LiteralPath $requirementsFile)) {
    throw "缺少依赖文件: $requirementsFile"
}

if ($Recreate -and (Test-Path -LiteralPath $venvFullPath)) {
    Write-Host "Recreating audio venv: $venvFullPath" -ForegroundColor Yellow
    Remove-Item -LiteralPath $venvFullPath -Recurse -Force
}

if (-not (Test-Path -LiteralPath $venvFullPath)) {
    Write-Host "Creating audio venv: $venvFullPath (python $PythonVersion)" -ForegroundColor Cyan
    & uv venv $venvFullPath --python $PythonVersion
}

$pythonExe = Join-Path $venvFullPath "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    $pythonExe = Join-Path $venvFullPath "bin\python"
}
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "未找到音频环境 Python: $venvFullPath"
}

Write-Host "Installing common audio deps..." -ForegroundColor Cyan
& uv pip install --python $pythonExe -r $requirementsFile

if ($CpuOnly) {
    Write-Host "Installing CPU torch stack..." -ForegroundColor Cyan
    & uv pip install --python $pythonExe "torch==2.8.0" "torchvision==0.23.0" "torchaudio==2.8.0" "onnxruntime>=1.24.0"
}
else {
    Write-Host "Installing CUDA torch stack (cu128)..." -ForegroundColor Cyan
    & uv pip install --python $pythonExe --index-url https://download.pytorch.org/whl/cu128 "torch==2.8.0+cu128" "torchvision==0.23.0+cu128" "torchaudio==2.8.0+cu128"
}

if ($LASTEXITCODE -ne 0) {
    throw "音频环境安装失败，退出码: $LASTEXITCODE"
}

$resolvedPython = (Resolve-Path $pythonExe).Path
Write-Host ""
Write-Host "Audio venv ready." -ForegroundColor Green
Write-Host "Python: $resolvedPython" -ForegroundColor Green
Write-Host "建议设置环境变量（可选）:" -ForegroundColor Yellow
Write-Host "  `$env:VIDEO_DUB_AUDIO_PYTHON=`"$resolvedPython`"" -ForegroundColor Yellow
