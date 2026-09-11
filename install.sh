#!/usr/bin/env bash
set -e

echo "========================================="
echo "  OpenCode Faster-Whisper Installer (macOS/Linux)"
echo "========================================="

# 1. Check opencode CLI
if ! command -v opencode &>/dev/null; then
    echo "[!] Warning: 'opencode' CLI not found in PATH."
fi

# 2. Check Python
PYTHON_CMD=""
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo "[-] Error: Python 3 is required but was not found in PATH."
    exit 1
fi

echo "[*] Checking Python dependencies..."
if ! "$PYTHON_CMD" -c "import sounddevice, numpy, faster_whisper" 2>/dev/null; then
    echo "[*] Installing Python packages (sounddevice, numpy, faster-whisper)..."
    "$PYTHON_CMD" -m pip install sounddevice numpy faster-whisper
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 3. Build plugin bundle
if command -v bun &>/dev/null; then
    echo "[*] Building plugin bundle with bun..."
    bun run build
elif command -v npm &>/dev/null; then
    echo "[*] Building plugin bundle with npm..."
    npm run build
elif [ -f "$SCRIPT_DIR/dist/index.js" ]; then
    echo "[*] Using pre-bundled dist/index.js..."
else
    echo "[-] Neither 'bun' nor 'npm' found to build dist/index.js."
    exit 1
fi

# 4. Target directories
PLUGIN_DIR="$HOME/.config/opencode/plugin"
SCRIPTS_DIR="$HOME/.config/opencode/scripts"

mkdir -p "$PLUGIN_DIR" "$SCRIPTS_DIR"

cp "$SCRIPT_DIR/dist/index.js" "$PLUGIN_DIR/whisper.js"
echo "[+] Plugin copied to $PLUGIN_DIR/whisper.js"

cp -r "$SCRIPT_DIR/scripts/"* "$SCRIPTS_DIR/"
echo "[+] Worker scripts copied to $SCRIPTS_DIR"

# 5. Check if local model exists
MODEL_DIR="$SCRIPT_DIR/models/base"
if [ ! -d "$MODEL_DIR" ]; then
    echo ""
    echo "[i] No offline model detected in 'models/base'."
    echo "    You can download it with:"
    echo "    $PYTHON_CMD scripts/download_model.py --model base --source modelscope"
    echo "    Or download manually from ModelScope and place into:"
    echo "    $MODEL_DIR"
fi

echo ""
echo "========================================="
echo "  Installation completed successfully!"
echo "  Start OpenCode and use /whisper or voice dictation."
echo "========================================="
