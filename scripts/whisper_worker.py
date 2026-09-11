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

# Fix Windows console / file redirection UnicodeEncodeError with emojis (charmap / cp1252)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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
    silence_timeout: float = 1.2,
    max_wait_speech: float = 10.0,
    sample_rate: int = 16000,
    language: str = "es",
    input_device: str = None,
    is_worker: bool = False,
) -> str:
    """
    Record audio from default microphone using smart silence detection.
    - Plays audio chime and shows system notification.
    - Auto-detects speech onset and terminates when user finishes speaking.
    - If in an interactive TTY (standalone), allows pressing [Enter] to stop.
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
        dev_default_sr = int(input_info.get('default_samplerate', sample_rate))
    except Exception as e:
        input_info = {}
        mic_name = f"Default (query error: {e})"
        dev_default_sr = sample_rate

    # Check supported samplerate
    actual_samplerate = sample_rate
    try:
        sd.check_input_settings(device=device_id, samplerate=sample_rate, channels=1, dtype="float32")
    except Exception as sr_err:
        print(f"[OpenCode Whisper] ⚠️ Frecuencia {sample_rate}Hz no soportada ({sr_err}). Usando {dev_default_sr}Hz.")
        actual_samplerate = dev_default_sr

    q = queue.Queue()
    stop_event = threading.Event()
    callback_count = 0

    def callback(indata, frames, time_info, status):
        nonlocal callback_count
        callback_count += 1
        if status:
            print(f"[OpenCode Whisper] Audio callback status: {status}")
        q.put(indata.copy())

    is_es = (language == "es")
    prompt_msg = "🎙️  [OpenCode Whisper] Escuchando... Di tu instrucción ahora." if is_es else "🎙️  [OpenCode Whisper] Listening... Speak your prompt now."
    print("\n" + "="*55)
    print(prompt_msg)
    print(f"🎤 [OpenCode Whisper] Micrófono: {mic_name} (ID: {device_id}) | Freq: {actual_samplerate}Hz")
    print("="*55)

    # Audio cue & desktop notification
    listen_notify = "Escuchando tu voz... Habla ahora." if is_es else "Listening for your voice... Speak now."
    notify("🎙️ OpenCode Whisper", listen_notify, sound="Tink")

    # Interactive Enter listener (ONLY in interactive standalone terminal, NEVER as background worker)
    if not is_worker and not duration and sys.stdin and sys.stdin.isatty():
        def wait_for_enter():
            try:
                line = sys.stdin.readline()
                if not line:  # EOF reached (stream closed or detached), ignore
                    return
            except Exception:
                return
            stop_event.set()
        threading.Thread(target=wait_for_enter, daemon=True).start()

    temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    temp_wav_path = temp_wav.name
    temp_wav.close()

    recorded_chunks = []
    start_time = time.time()
    last_progress_log = start_time
    speech_started = False
    silence_start_time = None

    # Use float32 with 1024 blocksize
    block_size = 1024
    ambient_samples = []

    # Configurable energy threshold via env
    env_thresh = os.environ.get("WHISPER_ENERGY_THRESHOLD")
    custom_threshold = float(env_thresh) if env_thresh else None
    threshold = custom_threshold if custom_threshold is not None else 0.003

    with sd.InputStream(device=device_id, samplerate=actual_samplerate, channels=1, dtype="float32", blocksize=block_size, callback=callback):
        while not stop_event.is_set():
            now = time.time()
            elapsed = now - start_time

            if duration and elapsed >= duration:
                break

            # Timeout after max_wait_speech (e.g. 10s) if user stopped or never spoke
            if elapsed >= max_wait_speech and not speech_started:
                print("⏱️ [OpenCode Whisper] Tiempo límite alcanzado. Procesando audio grabado...")
                break

            try:
                chunk = q.get(timeout=0.15)
                recorded_chunks.append(chunk)

                # Calculate normalized RMS
                energy = float(np.sqrt(np.mean(chunk ** 2)))

                if custom_threshold is None:
                    if elapsed < 0.3:
                        ambient_samples.append(energy)
                        continue
                    elif len(ambient_samples) > 0:
                        # Cap ambient noise estimation so speech during initial ms doesn't spike threshold
                        ambient = float(np.mean(ambient_samples)) if ambient_samples else 0.001
                        ambient = min(ambient, 0.01)
                        # Lower threshold floor to 0.0015 for quiet microphones
                        threshold = max(ambient * 1.4, 0.0015)
                        print(f"[OpenCode Whisper] Calibración audio: ruido={ambient:.5f}, umbral={threshold:.5f}")
                        ambient_samples = []

                # Periodic progress logging in log file every 1.5s
                if now - last_progress_log >= 1.5:
                    last_progress_log = now
                    print(f"[OpenCode Whisper] Grabando... elapsed={elapsed:.1f}s | chunks={len(recorded_chunks)} | nivel_actual={energy:.5f} | umbral={threshold:.5f} | voz_detectada={speech_started}")

                if energy > threshold:
                    if not speech_started:
                        speech_started = True
                        print(f"🗣️  [OpenCode Whisper] Voz detectada (nivel: {energy:.5f} > {threshold:.5f})")
                    silence_start_time = None
                elif speech_started:
                    if silence_start_time is None:
                        silence_start_time = now
                    elif now - silence_start_time >= silence_timeout:
                        print("🤫 [OpenCode Whisper] Silencio detectado. Finalizando grabación...")
                        break

            except queue.Empty:
                pass

    play_sound("Pop")
    print("🛑 [OpenCode Whisper] Grabación finalizada. Transcribiendo...")
    notify("📝 OpenCode Whisper", "Transcribiendo tu voz...", sound="Pop")

    if not recorded_chunks:
        print(f"[OpenCode Whisper] ❌ No se capturó ningún fragmento de audio del micrófono.")
        print(f"   - Callbacks recibidos del sistema: {callback_count}")
        print(f"   - Tiempo transcurrido: {elapsed:.2f}s")
        print(f"   - Dispositivo: {mic_name} (ID: {device_id})")
        print(f"   - Frecuencia intentada: {actual_samplerate}Hz")
        if callback_count == 0:
            print(f"   - CAUSA: El sistema operativo no entregó buffers de audio (callback_count=0).")
            print(f"     Comprueba permisos del micrófono en el sistema o prueba otro ID con WHISPER_INPUT_DEVICE.")
        return ""

    audio_float = np.concatenate(recorded_chunks, axis=0).flatten()
    
    # Calculate raw volume statistics
    raw_max_amp = float(np.max(np.abs(audio_float))) if len(audio_float) > 0 else 0.0
    raw_avg_rms = float(np.sqrt(np.mean(audio_float ** 2))) if len(audio_float) > 0 else 0.0

    # Auto Gain Control (AGC) & Normalization
    gain_env = os.environ.get("WHISPER_AUDIO_GAIN", "auto")
    applied_gain = 1.0

    if gain_env.lower() != "off" and raw_max_amp > 1e-5:
        if gain_env.lower() == "auto":
            # If volume is low (peak < 0.25), scale up towards 0.80 peak (up to 50x safely)
            if raw_max_amp < 0.25:
                applied_gain = min(0.80 / raw_max_amp, 50.0)
                db_gain = 20 * np.log10(applied_gain) if applied_gain > 0 else 0
                print(f"[OpenCode Whisper] 🔊 Audio bajo detectado (pico: {raw_max_amp:.4f}). Auto-amplificando x{applied_gain:.1f} (+{db_gain:.1f} dB)...")
        else:
            try:
                applied_gain = float(gain_env)
                print(f"[OpenCode Whisper] 🔊 Aplicando ganancia manual x{applied_gain:.1f} (WHISPER_AUDIO_GAIN)...")
            except ValueError:
                applied_gain = 1.0

    if applied_gain != 1.0:
        audio_float = np.clip(audio_float * applied_gain, -1.0, 1.0)

    # Scale float32 to 16-bit PCM for WAV
    audio_int16 = np.clip(audio_float * 32767, -32768, 32767).astype(np.int16)

    # Write WAV file
    with wave.open(temp_wav_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(actual_samplerate)
        wf.writeframes(audio_int16.tobytes())

    duration_sec = len(audio_float) / actual_samplerate
    final_max_amp = float(np.max(np.abs(audio_float))) if len(audio_float) > 0 else 0.0
    final_avg_rms = float(np.sqrt(np.mean(audio_float ** 2))) if len(audio_float) > 0 else 0.0

    print(f"[OpenCode Whisper] Audio guardado: {duration_sec:.2f}s | RMS: {final_avg_rms:.4f} (original: {raw_avg_rms:.4f}) | Pico: {final_max_amp:.4f} (original: {raw_max_amp:.4f})")
    print(f"[OpenCode Whisper] Archivo temporal: {temp_wav_path}")

    # Guardar copia fija en ~/.config/opencode/last_recording.wav para inspección manual
    debug_wav = Path.home() / ".config" / "opencode" / "last_recording.wav"
    try:
        import shutil
        debug_wav.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(temp_wav_path, debug_wav)
        print(f"[OpenCode Whisper] 💾 COPIA GUARDADA PARA COMPROBAR SI SE TE ESCUCHA:")
        print(f"    -> {debug_wav.resolve()}")
    except Exception as copy_err:
        print(f"[OpenCode Whisper] No se pudo guardar copia de depuración: {copy_err}")

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

    print("\n" + "="*60)
    print(f"[OpenCode Whisper] Worker iniciado | PID: {os.getpid()} | Python: {sys.version.split()[0]}")
    print(f"[OpenCode Whisper] Plataforma: {sys.platform} | CWD: {Path.cwd()}")

    try:
        import sounddevice as sd
        devices = sd.query_devices()
        default_in = sd.default.device[0]
        def_name = devices[default_in]['name'] if default_in >= 0 and default_in < len(devices) else "Desconocido"
        print(f"[OpenCode Whisper] Dispositivo por defecto: [{default_in}] {def_name}")
        print("[OpenCode Whisper] Dispositivos de entrada detectados:")
        for idx, dev in enumerate(devices):
            if dev.get("max_input_channels", 0) > 0:
                mark = " [ACTIVO/DEFAULT]" if idx == default_in else ""
                print(f"   [{idx}] {dev['name']}{mark} (canales: {dev['max_input_channels']}, freq: {int(dev['default_samplerate'])}Hz)")
    except Exception as e:
        print(f"[OpenCode Whisper] Error enumerando dispositivos: {e}")
    print("="*60 + "\n")

    if args.list_devices:
        sys.exit(0)

    if args.summary:
        print(f"📢 [OpenCode Notification]: {args.summary}")

    model_target = resolve_model(args.model, args.model_path)

    is_worker = bool(args.response_file)

    temp_audio_created = False
    if args.audio_file and Path(args.audio_file).exists():
        audio_file = args.audio_file
    else:
        audio_file = record_audio(
            duration=args.duration,
            language=args.language,
            input_device=args.input_device,
            is_worker=is_worker,
        )
        temp_audio_created = True

    if not audio_file or not Path(audio_file).exists():
        print("[OpenCode Whisper] No valid audio file to transcribe.")
        if args.response_file:
            try:
                response_path = Path(args.response_file)
                response_path.parent.mkdir(parents=True, exist_ok=True)
                response_path.write_text("$$NO_SPEECH$$", encoding="utf-8")
            except Exception:
                pass
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
            out_text = text if text.strip() else "$$NO_SPEECH$$"
            response_path.write_text(out_text, encoding="utf-8")
            print(f"[OpenCode Whisper] Written to response file: {response_path}")
        else:
            print(text)

    except Exception as e:
        print(f"[OpenCode Whisper] Error during transcription: {e}")
        if args.response_file:
            try:
                response_path = Path(args.response_file)
                response_path.parent.mkdir(parents=True, exist_ok=True)
                response_path.write_text("$$NO_SPEECH$$", encoding="utf-8")
            except Exception:
                pass
        sys.exit(1)

    finally:
        if temp_audio_created and os.path.exists(audio_file):
            try:
                os.remove(audio_file)
            except:
                pass

if __name__ == "__main__":
    main()
