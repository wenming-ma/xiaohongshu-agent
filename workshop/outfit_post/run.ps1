# ================================================
# XHS Outfit Post 执行脚本
# 穿搭搭配帖子（含飞书交互和发布）
# ================================================
#
# 用法:
#   # Live 模式（飞书交互）
#   .\workshop\outfit_post\run.ps1
#
#   # Mock 模式（跳过飞书，用预设单品）
#   .\workshop\outfit_post\run.ps1 -Mock
#
#   # 不发布
#   .\workshop\outfit_post\run.ps1 -NoPublish
#
#   # 指定话题范围
#   .\workshop\outfit_post\run.ps1 -StartIndex 2 -Limit 1
# ================================================

param(
    [string]$TopicsFile = "",
    [int]$StartIndex = 1,
    [int]$Limit = 0,
    [int]$MaxRetries = 10,
    [int]$RetryDelay = 5,
    [int]$Sleep = 0,
    [switch]$Mock = $false,
    [switch]$NoPublish = $false,
    [switch]$NoFeishu = $false
)

$ErrorActionPreference = "Continue"

$scriptDir = $PSScriptRoot
$projectRoot = Split-Path -Parent (Split-Path -Parent $scriptDir)

$pyScript = Join-Path $scriptDir "run.py"
$resolvedTopicsFile = if ($TopicsFile) {
    if ([System.IO.Path]::IsPathRooted($TopicsFile)) { $TopicsFile } else { Join-Path $scriptDir $TopicsFile }
} else {
    Join-Path $scriptDir "topics.json"
}

$pyArgs = @($pyScript, "--topics-file", $resolvedTopicsFile, "--start-index", $StartIndex, "--max-retries", $MaxRetries, "--retry-delay", $RetryDelay)

if ($Sleep -gt 0) { $pyArgs += @("--sleep", $Sleep) }
if ($Limit -gt 0) { $pyArgs += @("--limit", $Limit) }
if ($Mock) { $pyArgs += "--mock" }
if ($NoPublish) { $pyArgs += "--no-publish" }
if ($NoFeishu) { $pyArgs += "--no-feishu" }

$topics = Get-Content -Raw -Path $resolvedTopicsFile -Encoding UTF8 | ConvertFrom-Json
$totalCount = $topics.Count
$endIndex = if ($Limit -gt 0) { [Math]::Min($StartIndex + $Limit - 1, $totalCount) } else { $totalCount }

$mode = if ($Mock) { "MOCK (预设单品)" } else { "LIVE (飞书交互)" }

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "XHS Outfit Post Runner" -ForegroundColor Cyan
Write-Host "Mode: $mode" -ForegroundColor Cyan
Write-Host "Topics file: $resolvedTopicsFile" -ForegroundColor Cyan
Write-Host "Topics: #$StartIndex ~ #$endIndex / $totalCount" -ForegroundColor Cyan
Write-Host "Publish: $(if ($NoPublish) { 'No' } else { 'Yes' })" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Push-Location $projectRoot

try {
    & uv run python @pyArgs
    $exitCode = $LASTEXITCODE

    Write-Host ""
    if ($exitCode -eq 0) {
        Write-Host "All topics completed successfully." -ForegroundColor Green
    } else {
        Write-Host "Some topics failed. Check logs for details." -ForegroundColor Yellow
    }
}
catch {
    Write-Host "Script execution error: $_" -ForegroundColor Red
    $exitCode = 2
}
finally {
    Pop-Location
}

exit $exitCode
