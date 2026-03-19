<#
.SYNOPSIS
    持久化包装器 - 自动重启 run_mixed_posts.py 并从上次断点继续。

.DESCRIPTION
    - 默认模式: --feishu-only
    - 通过 .mixed_posts_progress.json 记录已完成的帖子数量
    - Python 崩溃后自动从上次位置恢复
    - 传入 -Reset 可清除进度从头开始

.EXAMPLE
    .\workshop\run_mixed_posts.ps1
    .\workshop\run_mixed_posts.ps1 -Reset
    .\workshop\run_mixed_posts.ps1 -ExtraArgs "--no-publish","--strategy","original"
#>

param(
    [switch]$Reset,
    [string[]]$ExtraArgs
)

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StateFile = Join-Path $ScriptDir ".mixed_posts_progress.json"
$RestartDelay = 30

# ---------------------------------------------------------------------------
# Progress helpers
# ---------------------------------------------------------------------------

function Get-Progress {
    if (Test-Path $StateFile) {
        return Get-Content $StateFile -Raw | ConvertFrom-Json
    }
    return [PSCustomObject]@{ start_image = 1; start_article = 1 }
}

function Save-Progress($si, $sa) {
    [PSCustomObject]@{ start_image = [int]$si; start_article = [int]$sa } |
        ConvertTo-Json | Set-Content $StateFile -Encoding utf8
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 进度已保存: image=$si article=$sa"
}

# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

if ($Reset) {
    if (Test-Path $StateFile) {
        Remove-Item $StateFile -Force
        Write-Host "进度已重置"
    } else {
        Write-Host "无进度文件，无需重置"
    }
    exit 0
}

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

while ($true) {
    $prog = Get-Progress
    $si = [int]$prog.start_image
    $sa = [int]$prog.start_article

    $runTs = Get-Date

    Write-Host ""
    Write-Host ("=" * 60)
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 启动 run_mixed_posts.py"
    Write-Host "  --start-image $si --start-article $sa --feishu-only $ExtraArgs"
    Write-Host ("=" * 60)

    $pyArgs = @(
        "run", "python", "workshop/run_mixed_posts.py",
        "--start-image", $si,
        "--start-article", $sa,
        "--feishu-only"
    )
    if ($ExtraArgs) { $pyArgs += $ExtraArgs }

    & uv @pyArgs
    $ec = $LASTEXITCODE

    # 查找本轮产生的 summary 文件
    $newSummary = Get-ChildItem (Join-Path $ScriptDir "mixed_post_summary_*.json") -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -ge $runTs } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if ($newSummary) {
        $data = Get-Content $newSummary.FullName -Raw | ConvertFrom-Json
        $imgDone  = @($data.results | Where-Object { $_.post_type -eq "image" }).Count
        $artDone  = @($data.results | Where-Object { $_.post_type -eq "article" }).Count

        $si += $imgDone
        $sa += $artDone
        Save-Progress $si $sa

        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 本轮完成: 图文=$imgDone 长文=$artDone"
    } else {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 未检测到汇总文件（可能崩溃在写入前），保持当前进度"
    }

    # 正常结束
    if ($ec -eq 0) {
        Write-Host ""
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 全部任务已完成"
        # 清除进度文件
        if (Test-Path $StateFile) { Remove-Item $StateFile -Force }
        break
    }

    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 进程退出码=$ec，${RestartDelay}秒后重启..."
    Start-Sleep -Seconds $RestartDelay
}
