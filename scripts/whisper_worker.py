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

import subprocess

def notify(title: str, message: str, sound: str = None):
    """Display system notification and optional sound."""
    if sys.platform == "darwin":
        sound_clause = f' sound name "{sound}"' if sound else ''
        cmd = f'display notification "{message}" with title "{title}"{sound_clause}'
        try:
            subprocess.run(["osascript", "-e", cmd], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except:
            pass
    elif sys.platform == "win32":
        try:
            import winsound
            winsound.MessageBeep()
        except:
            pass
        ps_cmd = f'''
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
        $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
        $textNodes = $template.GetElementsByTagName("text")
        $textNodes.Item(0).AppendChild($template.CreateTextNode("{title}")) > $null
        $textNodes.Item(1).AppendChild($template.CreateTextNode("{message}")) > $null
        $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("OpenCode Whisper")
        $notification = [Windows.UI.Notifications.ToastNotification]::new($template)
        $notifier.Show($notification)
        '''
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except:
            pass
    else:
        try:
            subprocess.run(["notify-send", title, message], check=False)
        except:
            pass

def play_sound(sound_name: str):
    """Play audio cue."""
    if sys.platform == "darwin":
        sound_path = f"/System/Library/Sounds/{sound_name}.aiff"
        if os.path.exists(sound_path):
            try:
                subprocess.Popen(["afplay", sound_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except:
                pass
    elif sys.platform == "win32":
        try:
            import winsound
            if sound_name == "Tink":
                # Start listening tone (medium-high beep)
                winsound.Beep(1200, 150)
            elif sound_name == "Pop":
                # Stopped tone
                winsound.Beep(800, 150)
            elif sound_name == "Glass":
                # Success/completion tone
                winsound.Beep(1500, 200)
            else:
                winsound.MessageBeep()
        except:
            pass

def record_audio(
    duration: float = None,
    silence_timeout: float = 1.0,
    max_wait_speech: float = 10.0,
    sample_rate: int = 16000,
    language: str = "es",
    input_device: str = None
) -> str:
    """
    Record audio from default microphone using smart silence detection.
    - Plays audio chime and shows system notification.
    - Auto-detects speech onset and terminates when user finishes speaking (1.0s silence).
    - If in an interactive TTY, also allows pressing [Enter] to stop.
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

    # Determine input device
    device_id = None
    if input_device:
        try:
            device_id = int(input_device)
        except ValueError:
            device_id = input_device

    try:
        input_info = sd.query_devices(device=device_id, kind='input')
        mic_name = input_info.get('name', 'Default')
    except Exception as e:
        mic_name = f"Default (query error: {e})"

    q = queue.Queue()
    stop_event = threading.Event()

    def callback(indata, frames, time_info, status):
        if status:
            pass
        q.put(indata.copy())

    is_es = (language == "es")
    prompt_msg = "🎙️  [OpenCode Whisper] Escuchando... Di tu instrucción ahora." if is_es else "🎙️  [OpenCode Whisper] Listening... Speak your prompt now."
    print("\n" + "="*50)
    print(prompt_msg)
    print(f"🎤 [OpenCode Whisper] Micrófono en uso: {mic_name}")
    print("="*50)

    # Audio cue & desktop notification
    listen_notify = "Escuchando tu voz... Habla ahora." if is_es else "Listening for your voice... Speak now."
    notify("🎙️ OpenCode Whisper", listen_notify, sound="Tink")

    # Interactive Enter listener (only if attached to a real terminal)
    if not duration and sys.stdin and sys.stdin.isatty():
        def wait_for_enter():
            try:
                sys.stdin.readline()
            except:
                pass
            stop_event.set()
        threading.Thread(target=wait_for_enter, daemon=True).start()

    temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    temp_wav_path = temp_wav.name
    temp_wav.close()

    recorded_chunks = []
    start_time = time.time()
    speech_started = False
    silence_start_time = None

    # Noise floor calibration over first 300ms
    calibration_chunks = []
    threshold = 600.0

    chunk_duration = 0.1  # 100ms
    block_size = int(sample_rate * chunk_duration)

    with sd.InputStream(device=device_id, samplerate=sample_rate, channels=1, dtype="int16", blocksize=block_size, callback=callback):
        while not stop_event.is_set():
            now = time.time()
            elapsed = now - start_time

            # Fixed duration limit
            if duration and elapsed >= duration:
                break

            # Timeout if no speech detected at all
            if not speech_started and elapsed >= max_wait_speech:
                timeout_msg = "⏱️ [OpenCode Whisper] No se detectó voz dentro del tiempo límite." if is_es else "⏱️ [OpenCode Whisper] No speech detected within timeout."
                print(timeout_msg)
                break

            try:
                chunk = q.get(timeout=0.15)
                recorded_chunks.append(chunk)

                # Calculate RMS energy of chunk
                energy = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))

                # Calibrate noise floor
                if elapsed < 0.3:
                    calibration_chunks.append(energy)
                    continue
                elif len(calibration_chunks) > 0:
                    ambient = float(np.mean(calibration_chunks)) if calibration_chunks else 300.0
                    threshold = max(ambient * 2.2, 500.0)
                    calibration_chunks = []

                # Silence detection state machine
                if energy > threshold:
                    if not speech_started:
                        speech_started = True
                        detect_msg = "🗣️  [OpenCode Whisper] Voz detectada..." if is_es else "🗣️  [OpenCode Whisper] Speech detected..."
                        print(detect_msg)
                    silence_start_time = None
                elif speech_started:
                    if silence_start_time is None:
                        silence_start_time = now
                    elif now - silence_start_time >= silence_timeout:
                        silence_msg = "🤫 [OpenCode Whisper] Silencio detectado. Transcribiendo..." if is_es else "🤫 [OpenCode Whisper] Silence detected. Stopping recording..."
                        print(silence_msg)
                        break

            except queue.Empty:
                pass

    play_sound("Pop")
    stop_msg = "🛑 [OpenCode Whisper] Grabación finalizada. Transcribiendo..." if is_es else "🛑 [OpenCode Whisper] Recording stopped. Transcribing..."
    print(stop_msg)
    transcribing_notify = "Transcribiendo tu voz..." if is_es else "Transcribing your audio..."
    notify("📝 OpenCode Whisper", transcribing_notify, sound="Pop")

    if not recorded_chunks or not speech_started:
        no_speech_msg = "[OpenCode Whisper] No se capturó voz." if is_es else "[OpenCode Whisper] No speech was captured."
        print(no_speech_msg)
        return ""

    audio_data = np.concatenate(recorded_chunks, axis=0)

    # Write WAV file
    with wave.open(temp_wav_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(audio_data.tobytes())

    return temp_wav_path

def transcribe_audio(
    audio_path: str,
    model_id_or_path: str,
    device: str = "cpu",
    compute_type: str = "int8",
    language: str = None,
    beam_size: int = 1,
) -> str:
    """
    Transcribe audio file using faster-whisper.
    Uses greedy decoding (beam_size=1) and Silero vad_filter for ~5x faster inference.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("[OpenCode Whisper] 'faster-whisper' is not installed.")
        print("Please run: pip install faster-whisper")
        sys.exit(1)

    print(f"[OpenCode Whisper] Loading Whisper model ({device}, {compute_type}, beam={beam_size})...")
    model = WhisperModel(model_id_or_path, device=device, compute_type=compute_type, cpu_threads=4)

    kwargs = {}
    if language:
        kwargs["language"] = language

    segments, info = model.transcribe(
        audio_path,
        beam_size=beam_size,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=400),
        **kwargs
    )
    text_parts = [segment.text for segment in segments]
    full_text = " ".join(text_parts).strip()

    return full_text

def main():
    parser = argparse.ArgumentParser(description="Local Faster-Whisper worker for OpenCode")
    parser.add_argument("--list-devices", action="store_true", help="List available audio input devices and exit")
    parser.add_argument("--input-device", type=str, default=os.environ.get("WHISPER_INPUT_DEVICE", None), help="Microphone device name or index (default: system default)")
    parser.add_argument("--model", type=str, default=os.environ.get("WHISPER_MODEL", "base"), help="Model size or name (default: base)")
    parser.add_argument("--model-path", type=str, default=None, help="Explicit path to offline model directory")
    parser.add_argument("--audio-file", type=str, default=None, help="Path to existing audio file to transcribe")
    parser.add_argument("--duration", type=float, default=None, help="Recording duration in seconds (if omitted, waits for Enter)")
    parser.add_argument("--device", type=str, default=os.environ.get("WHISPER_DEVICE", "cpu"), choices=["cpu", "cuda", "auto"], help="Inference device")
    parser.add_argument("--compute-type", type=str, default=os.environ.get("WHISPER_COMPUTE_TYPE", "int8"), help="Compute type (e.g. int8, float16, float32)")
    parser.add_argument("--beam-size", type=int, default=int(os.environ.get("WHISPER_BEAM_SIZE", "1")), help="Beam size (1=greedy/fastest, 5=standard)")
    parser.add_argument("--language", type=str, default=os.environ.get("WHISPER_LANGUAGE", "es"), help="Language code (e.g. es, en, zh, auto)")
    parser.add_argument("--response-file", type=str, default=None, help="File to write the transcribed text to")
    parser.add_argument("--message-file", type=str, default=None, help="OpenCode message file containing task info")
    parser.add_argument("--summary", type=str, default=None, help="Summary of task event")

    args = parser.parse_args()

    if args.list_devices:
        try:
            import sounddevice as sd
            print("\nAvailable audio input devices:")
            devices = sd.query_devices()
            default_input = sd.default.device[0]
            for idx, dev in enumerate(devices):
                if dev.get("max_input_channels", 0) > 0:
                    mark = " [DEFAULT]" if idx == default_input else ""
                    print(f"  [{idx}] {dev['name']}{mark} (channels: {dev['max_input_channels']})")
            print("")
        except Exception as e:
            print(f"Error querying audio devices: {e}")
        sys.exit(0)

    if args.summary:
        print(f"\n📢 [OpenCode Notification]: {args.summary}")

    model_target = resolve_model(args.model, args.model_path)

    temp_audio_created = False
    if args.audio_file and Path(args.audio_file).exists():
        audio_file = args.audio_file
    else:
        audio_file = record_audio(duration=args.duration, language=args.language, input_device=args.input_device)
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
            beam_size=args.beam_size,
        )

        print(f"\n✨ [OpenCode Whisper Result]: \"{text}\"\n")
        notify("✅ OpenCode Whisper", f'"{text}"', sound="Glass")

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
