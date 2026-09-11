$ErrorActionPreference = "Stop"

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  OpenCode Faster-Whisper Installer (Windows)" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# 1. Check opencode CLI
if (-not (Get-Command opencode -ErrorAction SilentlyContinue)) {
    Write-Warning "opencode CLI not found in PATH. Make sure OpenCode is installed."
}

# 2. Check Python
$pythonCmd = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } elseif (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { $null }
if (-not $pythonCmd) {
    Write-Error "Python 3 is required but was not found in PATH. Please install Python 3.9+."
    exit 1
}

Write-Host "[*] Checking Python dependencies..." -ForegroundColor Yellow
& $pythonCmd -c "import sounddevice, numpy, faster_whisper" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[*] Installing required Python packages (sounddevice, numpy, faster-whisper)..." -ForegroundColor Yellow
    & $pythonCmd -m pip install sounddevice numpy faster-whisper
}

# 3. Build plugin if bun or npm is available
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir

if (-not (Test-Path "$scriptDir\dist\index.js")) {
    Write-Host "[*] Building plugin bundle..." -ForegroundColor Yellow
    if (Get-Command bun -ErrorAction SilentlyContinue) {
        bun run build
    } elseif (Get-Command npm -ErrorAction SilentlyContinue) {
        npm run build
    } else {
        Write-Error "Neither 'bun' nor 'npm' found to build dist/index.js. Please run npm run build first."
        exit 1
    }
}

# 4. Target plugin and script directories in user profile
$opencodeConfigDir = Join-Path $env:USERPROFILE ".config\opencode"
$pluginDir = Join-Path $opencodeConfigDir "plugin"
$scriptsTargetDir = Join-Path $opencodeConfigDir "scripts"

New-Item -ItemType Directory -Force -Path $pluginDir | Out-Null
New-Item -ItemType Directory -Force -Path $scriptsTargetDir | Out-Null

# Copy plugin bundle
Copy-Item "$scriptDir\dist\index.js" "$pluginDir\whisper.js" -Force
Write-Host "[+] Plugin copied to $pluginDir\whisper.js" -ForegroundColor Green

# Copy python workers and download scripts
Copy-Item "$scriptDir\scripts\*" "$scriptsTargetDir" -Recurse -Force
Write-Host "[+] Worker scripts copied to $scriptsTargetDir" -ForegroundColor Green

# 5. Check if local model exists
$modelDir = Join-Path $scriptDir "models\base"
if (-not (Test-Path $modelDir)) {
    Write-Host ""
    Write-Host "[i] No offline model detected in 'models/base'." -ForegroundColor Yellow
    Write-Host "    You can download it now with:" -ForegroundColor White
    Write-Host "    $pythonCmd scripts/download_model.py --model base --source modelscope" -ForegroundColor Cyan
    Write-Host "    Or for air-gapped setups, download manually from ModelScope and place files into:" -ForegroundColor White
    Write-Host "    $modelDir" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "  Installation completed successfully!" -ForegroundColor Green
Write-Host "  Start OpenCode and use /whisper or voice dictation." -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
