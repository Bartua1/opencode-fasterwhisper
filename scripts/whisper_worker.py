#!/usr/bin/env python3
"""
Local Faster-Whisper worker for OpenCode.
Records voice from microphone (or reads an audio file), transcribes locally using faster-whisper,
and outputs the result directly to OpenCode's response file.
"""

import os
import sys
import time
import queue
import argparse
from pathlib import Path

def resolve_model(model_name: str, explicit_path: str = None) -> str:
    """
    Resolve local model directory hierarchy.
    Checks explicit path -> env WHISPER_MODEL_PATH -> ./models/<size> -> ~/.cache/opencode-whisper/models/<size> -> online fallback.
    """
    candidates = []

    if explicit_path:
        candidates.append(Path(explicit_path))

    env_path = os.environ.get("WHISPER_MODEL_PATH")
    if env_path:
        candidates.append(Path(env_path))

    # Project-relative models directory
    project_root = Path(__file__).resolve().parent.parent
    candidates.append(project_root / "models" / model_name)

    # User cache directory
    user_cache = Path.home() / ".cache" / "opencode-whisper" / "models" / model_name
    candidates.append(user_cache)

    # Check candidates for local model files
    for path in candidates:
        if path.exists() and path.is_dir():
            # Check for standard CTranslate2 / faster-whisper files
            if (path / "model.bin").exists() or (path / "config.json").exists():
                print(f"[OpenCode Whisper] Using local offline model from: {path.resolve()}")
                return str(path.resolve())

    if os.environ.get("WHISPER_OFFLINE", "0") == "1":
        print(f"[OpenCode Whisper] ERROR: WHISPER_OFFLINE is set, but no local model found for '{model_name}'.")
        print(f"Please download the model manually from ModelScope:")
        print(f"  https://www.modelscope.cn/models/Systran/faster-whisper-{model_name}/files")
        print(f"and place the files into: {project_root / 'models' / model_name}")
        sys.exit(1)

    print(f"[OpenCode Whisper] No local model found in candidates, falling back to model identifier: '{model_name}'")
    return model_name

def record_audio(duration: float = None, sample_rate: int = 16000) -> str:
    """
    Record audio from default microphone using sounddevice or fallback.
    Records until Enter is pressed or fixed duration.
    """
    import tempfile
    import wave
    import threading

    try:
        import sounddevice as sd
        import numpy as np
    except ImportError:
        print("[OpenCode Whisper] 'sounddevice' or 'numpy' is not installed.")
        print("Please install requirements: pip install sounddevice numpy scipy")
        sys.exit(1)

    q = queue.Queue()
    stop_event = threading.Event()

    def callback(indata, frames, time_info, status):
        if status:
            pass
        q.put(indata.copy())

    print("\n" + "="*50)
    print("🎙️  [OpenCode Whisper] Listening...")
    if duration:
        print(f"Recording for {duration} seconds...")
    else:
        print("Speak your response. Press [ENTER] when done speaking:")
    print("="*50)

    # Input listener thread for Enter key
    def wait_for_enter():
        try:
            sys.stdin.readline()
        except:
            pass
        stop_event.set()

    if not duration:
        listener_thread = threading.Thread(target=wait_for_enter, daemon=True)
        listener_thread.start()

    temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    temp_wav_path = temp_wav.name
    temp_wav.close()

    recorded_chunks = []
    start_time = time.time()

    with sd.InputStream(samplerate=sample_rate, channels=1, dtype="int16", callback=callback):
        while not stop_event.is_set():
            if duration and (time.time() - start_time >= duration):
                break
            try:
                chunk = q.get(timeout=0.1)
                recorded_chunks.append(chunk)
            except queue.Empty:
                pass

    print("🛑 [OpenCode Whisper] Recording stopped. Transcribing...")

    if not recorded_chunks:
        print("[OpenCode Whisper] No audio captured.")
        return ""

    audio_data = np.concatenate(recorded_chunks, axis=0)

    # Write WAV file
    with wave.open(temp_wav_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(audio_data.tobytes())

    return temp_wav_path

def transcribe_audio(audio_path: str, model_id_or_path: str, device: str = "cpu", compute_type: str = "int8", language: str = None) -> str:
    """
    Transcribe audio file using faster-whisper.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("[OpenCode Whisper] 'faster-whisper' is not installed.")
        print("Please run: pip install faster-whisper")
        sys.exit(1)

    print(f"[OpenCode Whisper] Loading Whisper model ({device}, {compute_type})...")
    model = WhisperModel(model_id_or_path, device=device, compute_type=compute_type)

    kwargs = {}
    if language:
        kwargs["language"] = language

    segments, info = model.transcribe(audio_path, beam_size=5, **kwargs)
    text_parts = [segment.text for segment in segments]
    full_text = " ".join(text_parts).strip()

    return full_text

def main():
    parser = argparse.ArgumentParser(description="Local Faster-Whisper worker for OpenCode")
    parser.add_argument("--model", type=str, default=os.environ.get("WHISPER_MODEL", "base"), help="Model size or name (default: base)")
    parser.add_argument("--model-path", type=str, default=None, help="Explicit path to offline model directory")
    parser.add_argument("--audio-file", type=str, default=None, help="Path to existing audio file to transcribe")
    parser.add_argument("--duration", type=float, default=None, help="Recording duration in seconds (if omitted, waits for Enter)")
    parser.add_argument("--device", type=str, default=os.environ.get("WHISPER_DEVICE", "cpu"), choices=["cpu", "cuda", "auto"], help="Inference device")
    parser.add_argument("--compute-type", type=str, default=os.environ.get("WHISPER_COMPUTE_TYPE", "int8"), help="Compute type (e.g. int8, float16, float32)")
    parser.add_argument("--language", type=str, default=os.environ.get("WHISPER_LANGUAGE", None), help="Language code (e.g. en, es, zh, auto)")
    parser.add_argument("--response-file", type=str, default=None, help="File to write the transcribed text to")
    parser.add_argument("--message-file", type=str, default=None, help="OpenCode message file containing task info")
    parser.add_argument("--summary", type=str, default=None, help="Summary of task event")

    args = parser.parse_args()

    if args.summary:
        print(f"\n📢 [OpenCode Notification]: {args.summary}")

    model_target = resolve_model(args.model, args.model_path)

    temp_audio_created = False
    if args.audio_file and Path(args.audio_file).exists():
        audio_file = args.audio_file
    else:
        audio_file = record_audio(duration=args.duration)
        temp_audio_created = True

    if not audio_file or not Path(audio_file).exists():
        print("[OpenCode Whisper] No valid audio file to transcribe.")
        sys.exit(1)

    try:
        text = transcribe_audio(
            audio_path=audio_file,
            model_id_or_path=model_target,
            device=args.device,
            compute_type=args.compute_type,
            language=args.language,
        )

        print(f"\n✨ [OpenCode Whisper Result]: \"{text}\"\n")

        if args.response_file:
            response_path = Path(args.response_file)
            response_path.parent.mkdir(parents=True, exist_ok=True)
            response_path.write_text(text, encoding="utf-8")
            print(f"[OpenCode Whisper] Written to response file: {response_path}")
        else:
            print(text)

    finally:
        if temp_audio_created and os.path.exists(audio_file):
            try:
                os.remove(audio_file)
            except:
                pass

if __name__ == "__main__":
    main()
