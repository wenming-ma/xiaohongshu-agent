# ================================================
# XHS Article Post 批量执行脚本
# 仅调用 article_post agent，不经过 MasterAgent
# ================================================
#
# 用法:
#   .\workshop\run_article_posts.ps1
#   .\workshop\run_article_posts.ps1 -StartIndex 3
#   .\workshop\run_article_posts.ps1 -StartIndex 5 -Limit 2
#   .\workshop\run_article_posts.ps1 -Strategy repurpose_article
#   .\workshop\run_article_posts.ps1 -NoPublish
#   .\workshop\run_article_posts.ps1 -NoImage
#   .\workshop\run_article_posts.ps1 -Sleep 3600
# ================================================

param(
    [int]$StartIndex = 1,
    [int]$Limit = 0,
    [int]$MaxRetries = 3,
    [int]$RetryDelay = 10,
    [int]$Sleep = 0,
    [string]$TopicsFile = "",
    [ValidateSet("auto", "synthesize", "repurpose_article", "repurpose_video")]
    [string]$Strategy = "",
    [switch]$Publish,
    [switch]$NoPublish,
    [switch]$NoImage
)

$ErrorActionPreference = "Continue"

if ($Publish -and $NoPublish) {
    throw "不能同时指定 -Publish 和 -NoPublish"
}

$scriptDir = $PSScriptRoot
$projectRoot = Split-Path -Parent (Split-Path -Parent $scriptDir)

# 构建 Python 脚本参数
$pyScript = Join-Path $scriptDir "run.py"
$topicsFile = if ($TopicsFile -ne "") { $TopicsFile } else { Join-Path $scriptDir "topics.json" }
$pyArgs = @($pyScript, "--topics-file", $topicsFile, "--start-index", $StartIndex, "--max-retries", $MaxRetries, "--retry-delay", $RetryDelay)

if ($Sleep -gt 0) {
    $pyArgs += @("--sleep", $Sleep)
}

if ($Limit -gt 0) {
    $pyArgs += @("--limit", $Limit)
}

if ($Strategy -ne "") {
    $pyArgs += @("--strategy", $Strategy)
}

# Publish is OFF by default; use -Publish to enable
if ($Publish -and -not $NoPublish) {
    $pyArgs += "--publish"
}

if ($NoImage) {
    $pyArgs += "--no-image"
}

# 读取 article_topics.json 计算总数用于显示
$topics = Get-Content -Raw -Path $topicsFile -Encoding UTF8 | ConvertFrom-Json
$totalCount = $topics.Count

# 计算实际处理范围
$endIndex = if ($Limit -gt 0) { [Math]::Min($StartIndex + $Limit - 1, $totalCount) } else { $totalCount }

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "XHS Article Post Batch Runner" -ForegroundColor Cyan
Write-Host "Agent: article_post (direct)" -ForegroundColor Cyan
Write-Host "Topics file: $topicsFile" -ForegroundColor Cyan
Write-Host "Topics: #$StartIndex ~ #$endIndex / $totalCount" -ForegroundColor Cyan
Write-Host "Max retries: $MaxRetries" -ForegroundColor Cyan
Write-Host "Publish: $($Publish -and -not $NoPublish)" -ForegroundColor Cyan
Write-Host "Generate images: $(-not $NoImage)" -ForegroundColor Cyan
if ($Strategy -ne "") {
    Write-Host "Strategy override: $Strategy" -ForegroundColor Cyan
} else {
    Write-Host "Strategy: per-topic (from JSON)" -ForegroundColor Cyan
}
if ($Sleep -gt 0) {
    Write-Host "Sleep between topics: $([Math]::Round($Sleep / 60, 1)) min" -ForegroundColor Cyan
} else {
    Write-Host "Sleep between topics: none" -ForegroundColor Cyan
}
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
