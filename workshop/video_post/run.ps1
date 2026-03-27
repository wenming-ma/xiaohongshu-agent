# ================================================
# XHS Video Post 批量执行脚本
# 仅调用 video_post agent，不经过 MasterAgent
# ================================================
#
# 用法:
#   .\workshop\video_post\run.ps1
#   .\workshop\video_post\run.ps1 -StartIndex 2
#   .\workshop\video_post\run.ps1 -StartIndex 2 -Limit 1
#   .\workshop\video_post\run.ps1 -NoPublish
#   .\workshop\video_post\run.ps1 -Platforms tiktok,instagram -MaxVideos 3
#   .\workshop\video_post\run.ps1 -Sleep 3600
# ================================================

param(
    [string]$TopicsFile = "",
    [int]$StartIndex = 1,
    [int]$Limit = 0,
    [int]$MaxRetries = 10,
    [int]$RetryDelay = 5,
    [int]$Sleep = 0,
    [string]$Platforms = "",
    [int]$MaxVideos = 0,
    [switch]$NoPublish = $false,
    [switch]$NoFeishu = $false
)

$ErrorActionPreference = "Continue"

$scriptDir = $PSScriptRoot
$projectRoot = Split-Path -Parent (Split-Path -Parent $scriptDir)

# 默认注入 s2.cpp 配音环境变量（仅在当前会话未设置时生效）
function Set-DefaultEnv {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$Value
    )
    $current = [Environment]::GetEnvironmentVariable($Name, "Process")
    if ([string]::IsNullOrWhiteSpace($current)) {
        [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
    }
}

Set-DefaultEnv -Name "VIDEO_DUB_TTS_PROVIDER" -Value "s2cpp"
Set-DefaultEnv -Name "VIDEO_DUB_USE_SEPARATE_ENV" -Value "1"
Set-DefaultEnv -Name "VIDEO_DUB_REQUIRE_AUDIO_ENV" -Value "1"
Set-DefaultEnv -Name "S2CPP_TTS_BASE_URL" -Value "http://127.0.0.1:3030"
# 参考音频/文本已硬编码在 video_dubbing.py 中，无需在此设置
Set-DefaultEnv -Name "S2CPP_TTS_CONCURRENCY" -Value "1"
Set-DefaultEnv -Name "S2CPP_TTS_TIMEOUT_SECONDS" -Value "240"
Set-DefaultEnv -Name "S2CPP_TTS_MERGE_SEGMENTS" -Value "1"
Set-DefaultEnv -Name "S2CPP_TTS_MERGE_MAX_GAP" -Value "1.2"
Set-DefaultEnv -Name "S2CPP_TTS_MERGE_MAX_DURATION" -Value "12"
Set-DefaultEnv -Name "S2CPP_TTS_MERGE_MAX_CHARS" -Value "120"

# 若用户未显式指定 VIDEO_DUB_AUDIO_PYTHON，尝试自动指向 .venv-audio
$audioPythonConfigured = [Environment]::GetEnvironmentVariable("VIDEO_DUB_AUDIO_PYTHON", "Process")
if ([string]::IsNullOrWhiteSpace($audioPythonConfigured)) {
    $audioCandidateWin = Join-Path $projectRoot ".venv-audio\Scripts\python.exe"
    $audioCandidateUnix = Join-Path $projectRoot ".venv-audio/bin/python"
    if (Test-Path -LiteralPath $audioCandidateWin) {
        [Environment]::SetEnvironmentVariable("VIDEO_DUB_AUDIO_PYTHON", $audioCandidateWin, "Process")
    }
    elseif (Test-Path -LiteralPath $audioCandidateUnix) {
        [Environment]::SetEnvironmentVariable("VIDEO_DUB_AUDIO_PYTHON", $audioCandidateUnix, "Process")
    }
}

$pyScript = Join-Path $scriptDir "run.py"
$resolvedTopicsFile = if ($TopicsFile) {
    if ([System.IO.Path]::IsPathRooted($TopicsFile)) { $TopicsFile } else { Join-Path $scriptDir $TopicsFile }
} else {
    Join-Path $scriptDir "topics.json"
}

if (-not (Test-Path -LiteralPath $resolvedTopicsFile)) {
    Write-Host "Topics file not found: $resolvedTopicsFile" -ForegroundColor Red
    exit 2
}

$pyArgs = @($pyScript, "--topics-file", $resolvedTopicsFile, "--start-index", $StartIndex, "--max-retries", $MaxRetries, "--retry-delay", $RetryDelay)

if ($Sleep -gt 0) {
    $pyArgs += @("--sleep", $Sleep)
}

if ($Limit -gt 0) {
    $pyArgs += @("--limit", $Limit)
}

if ($Platforms -ne "") {
    $pyArgs += @("--platforms")
    $pyArgs += $Platforms.Split(",")
}

if ($MaxVideos -gt 0) {
    $pyArgs += @("--max-videos", $MaxVideos)
}

if ($NoPublish) {
    $pyArgs += "--no-publish"
}

if ($NoFeishu) {
    $pyArgs += "--no-feishu"
}

# 读取话题文件计算总数用于显示
try {
    $topics = Get-Content -Raw -Path $resolvedTopicsFile -Encoding UTF8 | ConvertFrom-Json
}
catch {
    Write-Host "Invalid topics JSON: $resolvedTopicsFile" -ForegroundColor Red
    Write-Host $_ -ForegroundColor Red
    exit 2
}
$totalCount = $topics.Count

$endIndex = if ($Limit -gt 0) { [Math]::Min($StartIndex + $Limit - 1, $totalCount) } else { $totalCount }

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "XHS Video Post Batch Runner" -ForegroundColor Cyan
Write-Host "Topics file: $resolvedTopicsFile" -ForegroundColor Cyan
Write-Host "Agent: video_post (direct)" -ForegroundColor Cyan
Write-Host "Topics: #$StartIndex ~ #$endIndex / $totalCount" -ForegroundColor Cyan
Write-Host "Max retries: $MaxRetries" -ForegroundColor Cyan
Write-Host "Publish: $(-not $NoPublish)" -ForegroundColor Cyan
Write-Host "TTS provider: $($env:VIDEO_DUB_TTS_PROVIDER)" -ForegroundColor Cyan
Write-Host "Dub separate env: $($env:VIDEO_DUB_USE_SEPARATE_ENV)" -ForegroundColor Cyan
if ($env:VIDEO_DUB_USE_SEPARATE_ENV -eq "1") {
    if ($env:VIDEO_DUB_AUDIO_PYTHON) {
        Write-Host "Dub Python: $($env:VIDEO_DUB_AUDIO_PYTHON)" -ForegroundColor Cyan
    } else {
        Write-Host "Dub Python: (auto detect .venv-audio)" -ForegroundColor Cyan
    }
}
if ($env:VIDEO_DUB_TTS_PROVIDER -eq "s2cpp") {
    Write-Host "S2CPP URL: $($env:S2CPP_TTS_BASE_URL)" -ForegroundColor Cyan
}
if ($Platforms -ne "") {
    Write-Host "Platforms override: $Platforms" -ForegroundColor Cyan
}
if ($MaxVideos -gt 0) {
    Write-Host "Max videos override: $MaxVideos" -ForegroundColor Cyan
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
    $runStartedAt = Get-Date
    & uv run python @pyArgs
    $exitCode = $LASTEXITCODE

    Write-Host ""
    if ($exitCode -eq 0) {
        Write-Host "All topics completed successfully." -ForegroundColor Green
    } elseif ($exitCode -eq 1) {
        Write-Host "Some topics failed. Check logs for details." -ForegroundColor Yellow

        $latestFailureLog = Get-ChildItem -Path $scriptDir -File -Filter "video_post_failures_*.jsonl" -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -ge $runStartedAt } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        $latestFailedList = Get-ChildItem -Path $scriptDir -File -Filter "video_post_failed_*.json" -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -ge $runStartedAt } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1

        if ($latestFailureLog) {
            Write-Host "Failure stream: $($latestFailureLog.FullName)" -ForegroundColor Yellow
        }
        if ($latestFailedList) {
            Write-Host "Failure list: $($latestFailedList.FullName)" -ForegroundColor Yellow
        }
    } elseif ($exitCode -eq 2) {
        Write-Host "Batch crashed. Check crash log for details." -ForegroundColor Red

        $latestCrashLog = Get-ChildItem -Path $scriptDir -File -Filter "video_post_crash_*.json" -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -ge $runStartedAt } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        $latestSummary = Get-ChildItem -Path $scriptDir -File -Filter "video_post_summary_*.json" -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -ge $runStartedAt } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1

        if ($latestCrashLog) {
            Write-Host "Crash log: $($latestCrashLog.FullName)" -ForegroundColor Red
        }
        if ($latestSummary) {
            Write-Host "Summary: $($latestSummary.FullName)" -ForegroundColor Yellow
        }
    } else {
        Write-Host "Batch exited with code $exitCode. Check recent logs." -ForegroundColor Yellow

        $latestFailureLog = Get-ChildItem -Path $scriptDir -File -Filter "video_post_failures_*.jsonl" -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -ge $runStartedAt } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        $latestCrashLog = Get-ChildItem -Path $scriptDir -File -Filter "video_post_crash_*.json" -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -ge $runStartedAt } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1

        if ($latestFailureLog) {
            Write-Host "Failure stream: $($latestFailureLog.FullName)" -ForegroundColor Yellow
        }
        if ($latestCrashLog) {
            Write-Host "Crash log: $($latestCrashLog.FullName)" -ForegroundColor Red
        }
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
