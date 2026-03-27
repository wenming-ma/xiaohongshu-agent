param(
    [Parameter(Mandatory = $true)]
    [string]$Video,

    [Parameter(Mandatory = $true)]
    [string]$Srt,

    [Parameter(Mandatory = $true)]
    [string]$Output,

    [string]$WorkDir = "",
    [double]$BgVolume = 0.6,
    [ValidateSet("fish", "google", "s2cpp", "auto")]
    [string]$TtsProvider = "",
    [string]$FishUrl = "",
    [string]$FishReferenceId = "",
    [string]$S2CppUrl = "",
    [string]$S2CppReferenceAudio = "",
    [string]$S2CppReferenceTextFile = "",
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path "$PSScriptRoot\.."
Push-Location $root
try {
    if ($PythonExe -eq "") {
        $candidate = Join-Path $root ".venv-audio\Scripts\python.exe"
        if (Test-Path -LiteralPath $candidate) {
            $PythonExe = $candidate
        } else {
            $PythonExe = "python"
        }
    }

    $cmd = @(
        $PythonExe, "scripts/dub_video.py",
        "--video", $Video,
        "--srt", $Srt,
        "--output", $Output,
        "--bg-volume", "$BgVolume"
    )
    if ($WorkDir -ne "") {
        $cmd += @("--work-dir", $WorkDir)
    }
    if ($TtsProvider -ne "") {
        $cmd += @("--tts-provider", $TtsProvider)
    }
    if ($FishUrl -ne "") {
        $cmd += @("--fish-url", $FishUrl)
    }
    if ($FishReferenceId -ne "") {
        $cmd += @("--fish-reference-id", $FishReferenceId)
    }
    if ($S2CppUrl -ne "") {
        $cmd += @("--s2cpp-url", $S2CppUrl)
    }
    if ($S2CppReferenceAudio -ne "") {
        $cmd += @("--s2cpp-reference-audio", $S2CppReferenceAudio)
    }
    if ($S2CppReferenceTextFile -ne "") {
        $cmd += @("--s2cpp-reference-text-file", $S2CppReferenceTextFile)
    }

    Write-Host "Running: $($cmd -join ' ')"
    & $cmd[0] $cmd[1..($cmd.Length - 1)]
    if ($LASTEXITCODE -ne 0) {
        throw "配音命令执行失败，退出码: $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
