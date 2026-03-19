# ============================================================================
#  Agmercium Antigravity IDE History Recovery Tool — PowerShell Launcher
# ============================================================================

Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host "   Agmercium Antigravity IDE History Recovery Tool" -ForegroundColor Cyan
Write-Host "   Launcher for Windows (run.ps1)" -ForegroundColor Cyan
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host ""

# Locate Python
$pythonCmd = $null

foreach ($candidate in @("python", "python3", "py")) {
    try {
        $null = Get-Command $candidate -ErrorAction Stop
        $pythonCmd = $candidate
        break
    } catch {
        continue
    }
}

if (-not $pythonCmd) {
    Write-Host "[ERROR] Python is not installed or not in your PATH." -ForegroundColor Red
    Write-Host "        Please install Python 3.7+ from https://www.python.org/downloads/" -ForegroundColor Red
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "[INFO ] Using: $pythonCmd" -ForegroundColor Green
& $pythonCmd --version
Write-Host ""

# Run the recovery script from the same directory as this PowerShell script
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$recoveryScript = Join-Path $scriptDir "antigravity_recover.py"

if (-not (Test-Path $recoveryScript)) {
    Write-Host "[ERROR] antigravity_recover.py not found at: $recoveryScript" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

& $pythonCmd $recoveryScript @args

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] The recovery script exited with an error (code $LASTEXITCODE)." -ForegroundColor Red
    Write-Host ""
}

Read-Host "Press Enter to exit"
