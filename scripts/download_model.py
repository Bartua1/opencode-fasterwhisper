#!/usr/bin/env python3
"""
Model download helper for OpenCode Faster-Whisper.
Supports downloading from ModelScope (China/offline-friendly) and Hugging Face.
"""

import os
import sys
import argparse
from pathlib import Path

MODELS_MODELSCOPE = {
    "tiny": "Systran/faster-whisper-tiny",
    "tiny.en": "Systran/faster-whisper-tiny.en",
    "base": "Systran/faster-whisper-base",
    "base.en": "Systran/faster-whisper-base.en",
    "small": "Systran/faster-whisper-small",
    "small.en": "Systran/faster-whisper-small.en",
    "medium": "Systran/faster-whisper-medium",
    "medium.en": "Systran/faster-whisper-medium.en",
    "large-v2": "Systran/faster-whisper-large-v2",
    "large-v3": "Systran/faster-whisper-large-v3",
}

MODELS_HF = {
    "tiny": "Systran/faster-whisper-tiny",
    "tiny.en": "Systran/faster-whisper-tiny.en",
    "base": "Systran/faster-whisper-base",
    "base.en": "Systran/faster-whisper-base.en",
    "small": "Systran/faster-whisper-small",
    "small.en": "Systran/faster-whisper-small.en",
    "medium": "Systran/faster-whisper-medium",
    "medium.en": "Systran/faster-whisper-medium.en",
    "large-v2": "Systran/faster-whisper-large-v2",
    "large-v3": "Systran/faster-whisper-large-v3",
}

def print_manual_instructions(model_name: str, output_dir: Path):
    model_id = MODELS_MODELSCOPE.get(model_name, f"Systran/faster-whisper-{model_name}")
    url = f"https://www.modelscope.cn/models/{model_id}/files"
    print("\n" + "="*60)
    print("MANUAL DOWNLOAD INSTRUCTIONS (Offline / No Internet on target machine):")
    print("="*60)
    print(f"1. On a machine with browser access, open ModelScope:")
    print(f"   {url}")
    print(f"2. Download the required model files:")
    print(f"   - model.bin")
    print(f"   - config.json")
    print(f"   - tokenizer.json")
    print(f"   - vocabulary.json (or vocabulary.txt)")
    print(f"3. Copy the downloaded files into this folder on your laptop:")
    print(f"   {output_dir.resolve()}")
    print("="*60 + "\n")

def download_from_modelscope(model_name: str, output_dir: Path):
    model_id = MODELS_MODELSCOPE.get(model_name, f"Systran/faster-whisper-{model_name}")
    print(f"[*] Downloading '{model_id}' from ModelScope into: {output_dir}")
    try:
        from modelscope import snapshot_download
        downloaded_dir = snapshot_download(model_id, local_dir=str(output_dir))
        print(f"[+] Download complete: {downloaded_dir}")
        return True
    except ImportError:
        print("[!] The 'modelscope' Python package is not installed.")
        print("    Run: pip install modelscope")
        print_manual_instructions(model_name, output_dir)
        return False
    except Exception as e:
        print(f"[!] Error downloading from ModelScope: {e}")
        print_manual_instructions(model_name, output_dir)
        return False

def download_from_huggingface(model_name: str, output_dir: Path):
    model_id = MODELS_HF.get(model_name, f"Systran/faster-whisper-{model_name}")
    print(f"[*] Downloading '{model_id}' from Hugging Face into: {output_dir}")
    try:
        from huggingface_hub import snapshot_download
        downloaded_dir = snapshot_download(model_id, local_dir=str(output_dir))
        print(f"[+] Download complete: {downloaded_dir}")
        return True
    except ImportError:
        print("[!] The 'huggingface_hub' Python package is not installed.")
        print("    Run: pip install huggingface_hub")
        return False
    except Exception as e:
        print(f"[!] Error downloading from Hugging Face: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Download faster-whisper models (ModelScope / Hugging Face)")
    parser.add_argument(
        "--model",
        type=str,
        default="base",
        choices=list(MODELS_MODELSCOPE.keys()),
        help="Whisper model size (default: base)"
    )
    parser.add_argument(
        "--source",
        type=str,
        default="modelscope",
        choices=["modelscope", "huggingface", "manual"],
        help="Model source (default: modelscope for China/offline access)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output directory (default: ./models/<model>)"
    )

    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    output_dir = Path(args.output) if args.output else project_root / "models" / args.model
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.source == "manual":
        print_manual_instructions(args.model, output_dir)
        return

    if args.source == "modelscope":
        success = download_from_modelscope(args.model, output_dir)
        if not success:
            sys.exit(1)
    elif args.source == "huggingface":
        success = download_from_huggingface(args.model, output_dir)
        if not success:
            sys.exit(1)

if __name__ == "__main__":
    main()
