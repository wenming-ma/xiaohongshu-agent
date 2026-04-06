# ================================================
# XHS Outfit Post 执行脚本
# 默认：生成内容+图片 → 发送飞书审核（不发布小红书）
# 加 -Publish 才发布到小红书
# ================================================
#
# 用法:
#   # 默认：飞书审核模式
#   .\workshop\outfit_post\run.ps1
#
#   # Mock 模式（跳过飞书讨论，用预设单品）
#   .\workshop\outfit_post\run.ps1 -Mock
#
#   # 发布到小红书
#   .\workshop\outfit_post\run.ps1 -Publish
#
#   # 指定范围
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
    [switch]$Publish = $false,
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
if ($Publish) { $pyArgs += "--publish" }
if ($NoFeishu) { $pyArgs += "--no-feishu" }

$topics = Get-Content -Raw -Path $resolvedTopicsFile -Encoding UTF8 | ConvertFrom-Json
$totalCount = $topics.Count
$endIndex = if ($Limit -gt 0) { [Math]::Min($StartIndex + $Limit - 1, $totalCount) } else { $totalCount }

$mode = if ($Mock) { "MOCK" } else { "LIVE" }
$target = if ($Publish) { "发布到小红书" } else { "仅飞书审核" }

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "XHS Outfit Post Runner" -ForegroundColor Cyan
Write-Host "Mode: $mode / $target" -ForegroundColor Cyan
Write-Host "Topics file: $resolvedTopicsFile" -ForegroundColor Cyan
Write-Host "Topics: #$StartIndex ~ #$endIndex / $totalCount" -ForegroundColor Cyan
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
