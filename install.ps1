$ErrorActionPreference = "Stop"

if (-not (Get-Command opencode -ErrorAction SilentlyContinue)) {
    Write-Error "opencode CLI not found. Install from https://opencode.ai first."
    exit 1
}

opencode plugin -g -f @superwhisper/opencode

try {
    Start-Process "superwhisper://agent-installed?agent=opencode"
} catch {
    Write-Host "Plugin installed. Please open Superwhisper to complete setup."
}
