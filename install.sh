#!/bin/bash
set -e

if ! command -v opencode &>/dev/null; then
    echo "opencode CLI not found. Install from https://opencode.ai first." >&2
    exit 1
fi

opencode plugin -g -f @superwhisper/opencode </dev/null

if command -v open &>/dev/null; then
    open "superwhisper://agent-installed?agent=opencode"
elif command -v cmd.exe &>/dev/null; then
    cmd.exe /c start "" "superwhisper://agent-installed?agent=opencode"
elif command -v xdg-open &>/dev/null; then
    xdg-open "superwhisper://agent-installed?agent=opencode"
fi
