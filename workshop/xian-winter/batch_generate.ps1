# ================================================
# Xiaohongshu Batch Generation Script
# Theme: Xi'an Winter Travel Guide Series
# ================================================

$MaxRetries = 3
$RetryDelaySeconds = 5

# Get script directory and project root
$scriptDir = $PSScriptRoot
$projectRoot = Split-Path -Parent (Split-Path -Parent $scriptDir)

# Read topics from JSON file
$jsonPath = Join-Path $scriptDir "topics.json"
$topics = Get-Content -Raw -Path $jsonPath -Encoding UTF8 | ConvertFrom-Json

# Change to project root directory
Push-Location $projectRoot

# Statistics
$totalCount = $topics.Count
$successCount = 0
$failedTopics = @()

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Starting Xiaohongshu batch generation" -ForegroundColor Cyan
Write-Host "Theme: Xi'an Winter Travel Guide" -ForegroundColor Cyan
Write-Host "Total: $totalCount topics" -ForegroundColor Cyan
Write-Host "Max retries: $MaxRetries" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

for ($i = 0; $i -lt $topics.Count; $i++) {
    $item = $topics[$i]
    $topic = $item.topic
    $audience = $item.audience
    $currentNum = $i + 1
    
    Write-Host "[$currentNum/$totalCount] Topic: $topic" -ForegroundColor Yellow
    Write-Host "Audience: $audience" -ForegroundColor Gray
    
    $success = $false
    $retryCount = 0
    
    while (-not $success -and $retryCount -lt $MaxRetries) {
        $retryCount++
        
        if ($retryCount -gt 1) {
            Write-Host "  Retry #$retryCount..." -ForegroundColor Magenta
            Start-Sleep -Seconds $RetryDelaySeconds
        }
        
        try {
            Write-Host "  Running: uv run python -m src.main --topic `"$topic`" --audience `"$audience`"" -ForegroundColor DarkGray
            
            # Execute command
            & uv run python -m src.main --topic "$topic" --audience "$audience"
            
            if ($LASTEXITCODE -eq 0) {
                $success = $true
                $successCount++
                Write-Host "  OK" -ForegroundColor Green
            } else {
                Write-Host "  FAILED (exit code: $LASTEXITCODE)" -ForegroundColor Red
            }
        }
        catch {
            Write-Host "  ERROR: $_" -ForegroundColor Red
        }
    }
    
    if (-not $success) {
        Write-Host "  Max retries reached, skipping..." -ForegroundColor Red
        $failedTopics += $item
    }
    
    Write-Host ""
}

# Output statistics
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Batch generation completed!" -ForegroundColor Cyan
Write-Host "Success: $successCount / $totalCount" -ForegroundColor Green
$failColor = if ($failedTopics.Count -gt 0) { "Red" } else { "Green" }
Write-Host "Failed: $($failedTopics.Count) / $totalCount" -ForegroundColor $failColor
Write-Host "========================================" -ForegroundColor Cyan

# If there are failed topics, output details
if ($failedTopics.Count -gt 0) {
    Write-Host ""
    Write-Host "Failed topics:" -ForegroundColor Red
    foreach ($failed in $failedTopics) {
        Write-Host "  - $($failed.topic)" -ForegroundColor Red
    }
    
    # Save failed list to file (in script folder)
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $failedLogPath = Join-Path $scriptDir "failed_topics_$timestamp.json"
    $failedTopics | ConvertTo-Json -Depth 10 | Out-File -FilePath $failedLogPath -Encoding UTF8
    Write-Host ""
    Write-Host "Failed topics saved to: $failedLogPath" -ForegroundColor Yellow
}

# Restore original directory
Pop-Location
