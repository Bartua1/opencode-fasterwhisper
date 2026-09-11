# opencode-faster-whisper

100% local voice integration plugin for [OpenCode](https://opencode.ai), powered by **Faster-Whisper** and **CTranslate2**.

> **Note**: This project is a fork of [superultrainc/opencode-superwhisper](https://github.com/superultrainc/opencode-superwhisper). It transforms the integration into a **fully local, offline-capable voice coding loop** with support for both **ModelScope** (for environments without Hugging Face access) and Hugging Face, cross-platform Windows & macOS compatibility, and microphone capture.

---

## Features

- **100% Local & Private**: All speech recognition runs on your machine using CTranslate2/Faster-Whisper. No cloud APIs or third-party subscriptions required.
- **Offline & Restricted Network Ready**: Models can be auto-downloaded from **ModelScope CN** or **Hugging Face**, or **manually downloaded via browser** and dropped into a local folder.
- **Cross-Platform**: Tested and compatible with **Windows**, **macOS**, and **Linux**.
- **Low Latency & High Efficiency**: INT8 / FP16 quantized inference runs smoothly on standard CPU or GPU.
- **Hands-Free Coding Loop**: Voice responses to completed tasks, agent questions, and permission requests are transcribed and fed directly back into OpenCode.

---

## Architecture & How It Works

```
OpenCode Task Finishes (session.idle / question / permission)
                        │
                        ▼
            opencode-faster-whisper Plugin
                        │
                        ▼
             Local Python Whisper Worker
      ├── Plays audio chime / notification
      ├── Captures microphone input (cross-platform)
      ├── Transcribes speech locally with faster-whisper
      └── Writes text into session response file
                        │
                        ▼
      Plugin forwards transcribed prompt to OpenCode
```

---

## Requirements

1. **[OpenCode](https://opencode.ai)** v1.0+
2. **Python 3.8+** with the following packages:
   ```bash
   pip install -r requirements.txt
   ```
   *(Installs `faster-whisper`, `sounddevice`, `numpy`, `scipy`, and optional `modelscope`)*

---

## Model Setup (Auto & Manual Offline)

Whisper models come in various sizes (`tiny`, `base`, `small`, `medium`, `large-v3`). By default, `base` is used for balanced speed and accuracy.

### Option 1: Automatic Download from ModelScope (Recommended for China / No HuggingFace)
```bash
python scripts/download_model.py --model base --source modelscope
```

### Option 2: Automatic Download from Hugging Face
```bash
python scripts/download_model.py --model base --source huggingface
```

### Option 3: Manual Download (Air-Gapped / Restricted Laptops)
If your target machine cannot connect to Hugging Face:
1. On any device with internet, visit the ModelScope repository for your desired model:
   - Base: [https://www.modelscope.cn/models/Systran/faster-whisper-base/files](https://www.modelscope.cn/models/Systran/faster-whisper-base/files)
   - Small: [https://www.modelscope.cn/models/Systran/faster-whisper-small/files](https://www.modelscope.cn/models/Systran/faster-whisper-small/files)
   - Medium: [https://www.modelscope.cn/models/Systran/faster-whisper-medium/files](https://www.modelscope.cn/models/Systran/faster-whisper-medium/files)
2. Download the model files:
   - `model.bin`
   - `config.json`
   - `tokenizer.json`
   - `vocabulary.json` (or `vocabulary.txt`)
3. Copy the files into the `models/<size>` folder in this repo (e.g. `models/base/`) or any custom folder and set `WHISPER_MODEL_PATH=/path/to/folder`.

---

## Installation into OpenCode

### Method 1: Local Link / Install
Build the plugin and install it to OpenCode's local plugin directory:

**macOS / Linux:**
```bash
bun run install-local
# or copy dist/index.js ~/.config/opencode/plugin/whisper.js
```

**Windows (PowerShell):**
```powershell
.\install.ps1
```

### Method 2: OpenCode Configuration
Add the plugin to your OpenCode configuration (`~/.config/opencode/opencode.json` on macOS/Linux or `%USERPROFILE%\.config\opencode\opencode.json` on Windows):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["opencode-faster-whisper"]
}
```

---

## Configuration & Environment Variables

| Variable | Default | Description |
|---|---|---|
| `WHISPER_MODEL` | `base` | Model size (`tiny`, `base`, `small`, `medium`, `large-v3`) |
| `WHISPER_MODEL_PATH` | unset | Explicit path to an offline model directory |
| `WHISPER_DEVICE` | `cpu` | Inference device (`cpu`, `cuda`, `auto`) |
| `WHISPER_COMPUTE_TYPE` | `int8` | Precision quantization (`int8`, `float16`, `float32`) |
| `WHISPER_LANGUAGE` | unset (auto) | Language code (e.g. `en`, `es`, `zh`) |
| `WHISPER_OFFLINE` | `0` | Set to `1` to strictly disallow internet downloads |
| `PYTHON_BIN` | `python3` / `python` | Path to python executable |

---

## Events Handled

| OpenCode Event | Action |
|---|---|
| `session.idle` | Task completed; triggers local voice input and continues task loop |
| `session.error` | Error occurred; reports error and listens for corrective prompt |
| `permission.asked` | Tool approval requested; listens for voice approval (allow/always/deny) |
| `question.asked` | Agent asks a question; records spoken answer and sends to agent |

---

## Project Structure

```
opencode-faster-whisper/
├── src/
│   ├── index.ts          # Plugin entry point & OpenCode event router
│   ├── types.ts          # Cross-platform path & configuration types
│   ├── inbox.ts          # Cross-platform inbox & process management
│   ├── message.ts        # Message extraction & prompt parsing
│   ├── poll.ts           # File polling for voice response
│   └── normalize.ts      # Permission & question response parsing
├── scripts/
│   ├── download_model.py # ModelScope & HuggingFace downloader CLI
│   └── whisper_worker.py # Cross-platform mic recorder & faster-whisper engine
├── models/               # Local folder for manual/offline model weights
├── requirements.txt      # Python dependencies
├── package.json          # Plugin manifest
└── README.md             # Documentation
```

---

## License & Attribution

- Released under the MIT License.
- Upstream project: [superultrainc/opencode-superwhisper](https://github.com/superultrainc/opencode-superwhisper).
