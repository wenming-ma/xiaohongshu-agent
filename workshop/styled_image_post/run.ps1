# ================================================
# XHS Styled Image Post 批量执行脚本
# 调用 styled_image_post agent（支持参考图片）
# ================================================
#
# 用法:
#   .\workshop\run_styled_image_post.ps1
#   .\workshop\run_styled_image_post.ps1 -StartIndex 3
#   .\workshop\run_styled_image_post.ps1 -StartIndex 5 -Limit 2
#   .\workshop\run_styled_image_post.ps1 -TopicsFile styled_image_topics.json
#   .\workshop\run_styled_image_post.ps1 -Sleep 3600
# ================================================

param(
    [string]$TopicsFile = "",
    [int]$StartIndex = 1,
    [int]$Limit = 0,
    [int]$MaxRetries = 10,
    [int]$RetryDelay = 5,
    [int]$Sleep = 0,
    [switch]$NoFeishu = $false
)

$ErrorActionPreference = "Continue"

$scriptDir = $PSScriptRoot
$projectRoot = Split-Path -Parent (Split-Path -Parent $scriptDir)

# 构建 Python 脚本参数
$pyScript = Join-Path $scriptDir "run.py"
$resolvedTopicsFile = if ($TopicsFile) {
    if ([System.IO.Path]::IsPathRooted($TopicsFile)) { $TopicsFile } else { Join-Path $scriptDir $TopicsFile }
} else {
    Join-Path $scriptDir "topics.json"
}

$pyArgs = @($pyScript, "--topics-file", $resolvedTopicsFile, "--start-index", $StartIndex, "--max-retries", $MaxRetries, "--retry-delay", $RetryDelay)

if ($Sleep -gt 0) {
    $pyArgs += @("--sleep", $Sleep)
}

if ($Limit -gt 0) {
    $pyArgs += @("--limit", $Limit)
}

if ($NoFeishu) {
    $pyArgs += "--no-feishu"
}

# 读取话题文件计算总数用于显示
$topics = Get-Content -Raw -Path $resolvedTopicsFile -Encoding UTF8 | ConvertFrom-Json
$totalCount = $topics.Count

# 计算实际处理范围
$endIndex = if ($Limit -gt 0) { [Math]::Min($StartIndex + $Limit - 1, $totalCount) } else { $totalCount }

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "XHS Styled Image Post Batch Runner" -ForegroundColor Cyan
Write-Host "Topics file: $resolvedTopicsFile" -ForegroundColor Cyan
Write-Host "Agent: styled_image_post (with reference images)" -ForegroundColor Cyan
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
