# ================================================
# XHS Image Post 批量执行脚本
# 仅调用 image_post agent，不经过 MasterAgent
# ================================================
#
# 用法:
#   .\workshop\run_image_posts.ps1
#   .\workshop\run_image_posts.ps1 -StartIndex 3
#   .\workshop\run_image_posts.ps1 -StartIndex 5 -Limit 2
#   .\workshop\run_image_posts.ps1 -Sleep 3600   # 固定休眠（覆盖动态策略）
# ================================================

param(
    [int]$StartIndex = 1,
    [int]$Limit = 0,
    [int]$MaxRetries = 10,
    [int]$RetryDelay = 5,
    [int]$Sleep = 0
)

$ErrorActionPreference = "Continue"

$scriptDir = $PSScriptRoot
$projectRoot = Split-Path -Parent $scriptDir

# 构建 Python 脚本参数
$pyScript = Join-Path $scriptDir "run_image_posts.py"
$pyArgs = @($pyScript, "--start-index", $StartIndex, "--max-retries", $MaxRetries, "--retry-delay", $RetryDelay)

if ($Sleep -gt 0) {
    $pyArgs += @("--sleep", $Sleep)
}

if ($Limit -gt 0) {
    $pyArgs += @("--limit", $Limit)
}

# 读取 image_topics.json 计算总数用于显示
$topicsFile = Join-Path $scriptDir "image_topics.json"
$topics = Get-Content -Raw -Path $topicsFile -Encoding UTF8 | ConvertFrom-Json
$totalCount = $topics.Count

# 计算实际处理范围
$endIndex = if ($Limit -gt 0) { [Math]::Min($StartIndex + $Limit - 1, $totalCount) } else { $totalCount }

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "XHS Image Post Batch Runner" -ForegroundColor Cyan
Write-Host "Agent: image_post (direct)" -ForegroundColor Cyan
Write-Host "Topics: #$StartIndex ~ #$endIndex / $totalCount" -ForegroundColor Cyan
Write-Host "Max retries: $MaxRetries" -ForegroundColor Cyan
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
