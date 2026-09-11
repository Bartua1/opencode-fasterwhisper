#!/usr/bin/env python3
"""
Cross-platform persistent Faster-Whisper daemon for OpenCode.
Keeps Python and the WhisperModel warm in memory across requests.
Starts when OpenCode initializes and terminates cleanly when OpenCode exits.

Features:
- Parent watchdog: detects parent process termination via stdin EOF and PID polling (never leaves orphans).
- Pre-warms WhisperModel in background on boot for instant (~200ms) transcription.
- Non-blocking instant audio cues (macOS afplay, Windows winsound, Linux aplay/bell).
- Line-delimited JSON IPC over stdin/stdout.
"""

import os
import sys
import time
import json
import queue
import wave
import tempfile
import threading
import argparse
import subprocess
from pathlib import Path

# Fix Windows console UnicodeEncodeError (charmap / cp1252)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


LOG_FILE = Path.home() / ".config" / "opencode" / "whisper.log"
try:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
except Exception:
    pass


def log(msg: str):
    """Print log message to stderr and append to whisper.log."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] [OpenCode Whisper Daemon] {msg}\n"
    sys.stderr.write(formatted)
    sys.stderr.flush()
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(formatted)
    except Exception:
        pass


def send_json(data: dict):
    """Send JSON response to OpenCode via stdout."""
    try:
        line = json.dumps(data, ensure_ascii=False)
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    except Exception as e:
        log(f"Failed to send JSON to stdout: {e}")


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

    project_root = Path(__file__).resolve().parent.parent
    candidates.append(project_root / "models" / model_name)

    user_cache = Path.home() / ".cache" / "opencode-whisper" / "models" / model_name
    candidates.append(user_cache)

    for path in candidates:
        if path.exists() and path.is_dir():
            if (path / "model.bin").exists() or (path / "config.json").exists():
                log(f"Using local offline model: {path.resolve()}")
                return str(path.resolve())

    if os.environ.get("WHISPER_OFFLINE", "0") == "1":
        log(f"ERROR: WHISPER_OFFLINE is set, but no local model found for '{model_name}'.")
        sys.exit(1)

    log(f"Falling back to online/HF model identifier: '{model_name}'")
    return model_name


def play_sound(sound_name: str):
    """Play audio cue asynchronously without blocking the caller."""
    def _play():
        if sys.platform == "darwin":
            sound_path = f"/System/Library/Sounds/{sound_name}.aiff"
            if os.path.exists(sound_path):
                try:
                    subprocess.run(["afplay", sound_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                except Exception:
                    pass
        elif sys.platform == "win32":
            try:
                import winsound
                if sound_name == "Tink":
                    winsound.Beep(1200, 150)
                elif sound_name == "Pop":
                    winsound.Beep(800, 150)
                elif sound_name == "Glass":
                    winsound.Beep(1500, 200)
                else:
                    winsound.MessageBeep()
            except Exception:
                pass
        else:
            # Linux: try paplay or system bell
            try:
                for player in [["paplay", f"/usr/share/sounds/freedesktop/stereo/{sound_name.lower()}.oga"], ["aplay", "-q"]]:
                    if subprocess.call(["which", player[0]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                        subprocess.run(player, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                        break
            except Exception:
                pass

    threading.Thread(target=_play, daemon=True).start()


def notify_async(title: str, message: str):
    """Display OS desktop notification asynchronously in a background thread."""
    def _notify():
        try:
            if sys.platform == "darwin":
                cmd = f'display notification "{message}" with title "{title}"'
                subprocess.run(["osascript", "-e", cmd], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif sys.platform == "win32":
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
                subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.run(["notify-send", title, message], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    threading.Thread(target=_notify, daemon=True).start()


class WhisperDaemon:
    def __init__(self, model_name: str = "base", device: str = "cpu", compute_type: str = "int8", parent_pid: int = None):
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.parent_pid = parent_pid

        self.model = None
        self.model_ready = threading.Event()
        self.current_cancel_event = None
        self.is_busy = False
        self.lock = threading.Lock()

    def start_parent_watchdog(self):
        """Monitor parent process. If OpenCode terminates, die immediately."""
        def _watch():
            while True:
                time.sleep(1.0)
                if sys.platform != "win32":
                    try:
                        current_ppid = os.getppid()
                        if current_ppid == 1 or (self.parent_pid and current_ppid != self.parent_pid):
                            log(f"Parent process died (current ppid={current_ppid}). Exiting daemon.")
                            os._exit(0)
                    except Exception:
                        pass
                else:
                    if self.parent_pid:
                        try:
                            # On Windows, check if parent process is still alive
                            import ctypes
                            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                            SYNCHRONIZE = 0x00100000
                            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, self.parent_pid)
                            if not handle:
                                log(f"Parent PID {self.parent_pid} not accessible. Exiting daemon.")
                                os._exit(0)
                            ctypes.windll.kernel32.CloseHandle(handle)
                        except Exception:
                            pass

        threading.Thread(target=_watch, daemon=True).start()

    def preload_model(self):
        """Warm up WhisperModel in background thread."""
        def _loader():
            t0 = time.time()
            try:
                from faster_whisper import WhisperModel
                model_target = resolve_model(self.model_name)
                log(f"Pre-loading Whisper model '{self.model_name}' ({self.device}, {self.compute_type})...")
                self.model = WhisperModel(model_target, device=self.device, compute_type=self.compute_type, cpu_threads=4)
                self.model_ready.set()
                elapsed = time.time() - t0
                log(f"WhisperModel warm in RAM! Loaded in {elapsed:.2f}s.")
                send_json({"status": "ready", "model": self.model_name, "load_time_sec": round(elapsed, 2)})
            except Exception as e:
                log(f"Failed to preload WhisperModel: {e}")
                self.model_ready.set()
                send_json({"status": "model_error", "error": str(e)})

        threading.Thread(target=_loader, daemon=True).start()

    def record_and_transcribe(self, response_file: str, message_file: str = None, summary: str = None, language: str = "es", input_device: str = None):
        """Execute recording and transcription for a listen request."""
        import sounddevice as sd
        import numpy as np

        cancel_event = threading.Event()
        with self.lock:
            self.current_cancel_event = cancel_event
            self.is_busy = True

        try:
            # Play start cue instantly
            play_sound("Tink")
            is_es = (language == "es")
            notify_msg = "Escuchando tu voz... Habla ahora." if is_es else "Listening for your voice... Speak now."
            notify_async("🎙️ OpenCode Whisper", notify_msg)

            send_json({"status": "listening", "summary": summary})

            # Setup audio recording
            device_id = None
            if input_device:
                try:
                    device_id = int(input_device)
                except ValueError:
                    device_id = input_device

            sample_rate = 16000
            q = queue.Queue()

            def audio_callback(indata, frames, time_info, status):
                q.put(indata.copy())

            recorded_chunks = []
            start_time = time.time()
            last_progress_log = start_time
            speech_started = False
            silence_start_time = None
            silence_timeout = 1.2
            max_wait_speech = 10.0
            max_recording_time = 30.0
            ambient_samples = []

            custom_threshold = None
            env_thresh = os.environ.get("WHISPER_ENERGY_THRESHOLD")
            if env_thresh:
                try:
                    custom_threshold = float(env_thresh)
                except ValueError:
                    pass
            threshold = custom_threshold if custom_threshold is not None else 0.003

            # Open stream
            with sd.InputStream(device=device_id, samplerate=sample_rate, channels=1, dtype="float32", blocksize=1024, callback=audio_callback):
                while not cancel_event.is_set():
                    now = time.time()
                    elapsed = now - start_time

                    # Safety hard timeout: never record longer than 30s
                    if elapsed >= max_recording_time:
                        log(f"Límite máximo de grabación alcanzado ({max_recording_time:.0f}s). Finalizando.")
                        break

                    # Timeout if user never spoke within 10s
                    if elapsed >= max_wait_speech and not speech_started:
                        log("Tiempo límite de espera alcanzado sin detectar voz (10s).")
                        break

                    try:
                        chunk = q.get(timeout=0.15)
                        recorded_chunks.append(chunk)

                        energy = float(np.sqrt(np.mean(chunk ** 2)))

                        # Dynamic ambient noise calibration during first 0.25s
                        if custom_threshold is None:
                            if elapsed < 0.25:
                                ambient_samples.append(energy)
                                continue
                            elif len(ambient_samples) > 0:
                                ambient = float(np.mean(ambient_samples)) if ambient_samples else 0.001
                                ambient = min(ambient, 0.02)
                                threshold = max(ambient * 1.5, 0.0025)
                                log(f"Calibración de audio: ruido_base={ambient:.5f}, umbral_voz={threshold:.5f}")
                                ambient_samples = []

                        # Periodic progress logging every 1.5s
                        if now - last_progress_log >= 1.5:
                            last_progress_log = now
                            silence_dur = (now - silence_start_time) if silence_start_time else 0.0
                            log(f"Grabando... elapsed={elapsed:.1f}s | nivel={energy:.5f} | umbral={threshold:.5f} | voz_detectada={speech_started} | silencio={silence_dur:.1f}s")

                        if energy > threshold:
                            if not speech_started:
                                speech_started = True
                                log(f"Voz detectada! (nivel: {energy:.5f} > umbral: {threshold:.5f})")
                            silence_start_time = None
                        elif speech_started:
                            if silence_start_time is None:
                                silence_start_time = now
                            elif now - silence_start_time >= silence_timeout:
                                log(f"Silencio detectado ({silence_timeout}s). Finalizando grabación...")
                                break

                    except queue.Empty:
                        pass

            play_sound("Pop")

            if cancel_event.is_set():
                log("Listen request was cancelled.")
                send_json({"status": "cancelled"})
                return

            if not recorded_chunks:
                log("No audio chunks captured.")
                self._write_response(response_file, "$$NO_SPEECH$$")
                send_json({"status": "no_speech"})
                return

            # Wait for model if still preloading (up to 60s in case downloading)
            if not self.model_ready.is_set():
                log("Waiting for WhisperModel to finish preloading (may be downloading model files)...")
                self.model_ready.wait(timeout=60.0)

            if not self.model:
                log("ERROR: WhisperModel unavailable.")
                self._write_response(response_file, "$$NO_SPEECH$$")
                send_json({"status": "error", "error": "WhisperModel failed to load"})
                return

            notify_async("📝 OpenCode Whisper", "Transcribiendo tu voz..." if is_es else "Transcribing...")
            send_json({"status": "transcribing"})

            # Process audio
            audio_float = np.concatenate(recorded_chunks, axis=0).flatten()

            # Auto-Gain Control (AGC)
            raw_max_amp = float(np.max(np.abs(audio_float))) if len(audio_float) > 0 else 0.0
            if raw_max_amp > 1e-5 and raw_max_amp < 0.25:
                applied_gain = min(0.80 / raw_max_amp, 50.0)
                audio_float = np.clip(audio_float * applied_gain, -1.0, 1.0)

            audio_int16 = np.clip(audio_float * 32767, -32768, 32767).astype(np.int16)

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                temp_wav_path = tf.name

            # Save debug copy
            try:
                import shutil
                debug_wav = Path.home() / ".config" / "opencode" / "last_recording.wav"
                debug_wav.parent.mkdir(parents=True, exist_ok=True)
                with wave.open(str(debug_wav), "wb") as dwf:
                    dwf.setnchannels(1)
                    dwf.setsampwidth(2)
                    dwf.setframerate(sample_rate)
                    dwf.writeframes(audio_int16.tobytes())
                log(f"Copia de audio guardada en: {debug_wav}")
            except Exception as e:
                log(f"No se pudo guardar last_recording.wav: {e}")

            try:
                with wave.open(temp_wav_path, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    wf.writeframes(audio_int16.tobytes())

                # Transcribe with warm model
                t_trans_start = time.time()
                kwargs = {}
                if language:
                    kwargs["language"] = language

                beam_size = int(os.environ.get("WHISPER_BEAM_SIZE", "1"))
                segments, _ = self.model.transcribe(
                    temp_wav_path,
                    beam_size=beam_size,
                    vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=400),
                    **kwargs
                )
                text = " ".join(seg.text for seg in segments).strip()
                t_trans_elapsed = time.time() - t_trans_start

                log(f"Transcribed in {t_trans_elapsed:.2f}s: '{text}'")
                play_sound("Glass")
                notify_async("✅ OpenCode Whisper", f'"{text}"')

                out_text = text if text else "$$NO_SPEECH$$"
                self._write_response(response_file, out_text)
                send_json({"status": "transcribed", "text": text, "transcribe_time_sec": round(t_trans_elapsed, 2)})

            finally:
                if os.path.exists(temp_wav_path):
                    try:
                        os.remove(temp_wav_path)
                    except Exception:
                        pass

        except Exception as e:
            log(f"Error during record_and_transcribe: {e}")
            self._write_response(response_file, "$$NO_SPEECH$$")
            send_json({"status": "error", "error": str(e)})

        finally:
            with self.lock:
                self.is_busy = False
                self.current_cancel_event = None

    def cancel_current(self):
        """Cancel current ongoing recording if any."""
        with self.lock:
            if self.current_cancel_event and not self.current_cancel_event.is_set():
                self.current_cancel_event.set()
                log("Signaled cancellation to active recording.")

    def _write_response(self, response_file: str, text: str):
        if not response_file:
            return
        try:
            p = Path(response_file)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        except Exception as e:
            log(f"Failed to write response file {response_file}: {e}")

    def run(self):
        """Main loop: listen on stdin for JSON commands until EOF."""
        log("Daemon listening on stdin...")
        send_json({"status": "started", "pid": os.getpid()})

        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    # Stdin EOF: OpenCode closed or crashed
                    log("Stdin reached EOF (parent closed pipe). Terminating daemon cleanly.")
                    os._exit(0)

                line = line.strip()
                if not line:
                    continue

                try:
                    cmd_obj = json.loads(line)
                except Exception as parse_err:
                    log(f"Invalid JSON received: {line[:100]} — {parse_err}")
                    continue

                cmd = cmd_obj.get("cmd")

                if cmd == "ping":
                    send_json({"status": "pong", "ready": self.model_ready.is_set(), "busy": self.is_busy})

                elif cmd == "listen":
                    if self.is_busy:
                        log("Busy: cancelling previous recording to handle new listen request.")
                        self.cancel_current()
                        time.sleep(0.1)

                    resp_file = cmd_obj.get("response_file") or cmd_obj.get("responseFile")
                    msg_file = cmd_obj.get("message_file") or cmd_obj.get("messageFile")
                    summary = cmd_obj.get("summary")
                    lang = cmd_obj.get("language") or os.environ.get("WHISPER_LANGUAGE", "es")
                    input_dev = cmd_obj.get("input_device") or os.environ.get("WHISPER_INPUT_DEVICE")

                    # Run recording in separate thread so stdin remains responsive to 'cancel' or 'ping'
                    th = threading.Thread(
                        target=self.record_and_transcribe,
                        args=(resp_file, msg_file, summary, lang, input_dev),
                        daemon=True
                    )
                    th.start()

                elif cmd == "cancel":
                    self.cancel_current()
                    send_json({"status": "cancelled"})

                elif cmd == "quit" or cmd == "exit":
                    log("Explicit quit command received. Exiting.")
                    os._exit(0)

                else:
                    log(f"Unknown command: {cmd}")
                    send_json({"status": "unknown_command", "cmd": cmd})

            except KeyboardInterrupt:
                log("KeyboardInterrupt received. Exiting.")
                os._exit(0)
            except Exception as loop_err:
                log(f"Error in main loop: {loop_err}")


def main():
    parser = argparse.ArgumentParser(description="Cross-platform Faster-Whisper daemon for OpenCode")
    parser.add_argument("--model", type=str, default=os.environ.get("WHISPER_MODEL", "base"), help="Whisper model size")
    parser.add_argument("--device", type=str, default=os.environ.get("WHISPER_DEVICE", "cpu"), choices=["cpu", "cuda", "auto"], help="Device")
    parser.add_argument("--compute-type", type=str, default=os.environ.get("WHISPER_COMPUTE_TYPE", "int8"), help="Compute type")
    parser.add_argument("--parent-pid", type=int, default=None, help="Parent PID to monitor")

    args = parser.parse_args()

    daemon = WhisperDaemon(
        model_name=args.model,
        device=args.device,
        compute_type=args.compute_type,
        parent_pid=args.parent_pid
    )

    daemon.start_parent_watchdog()
    daemon.preload_model()
    daemon.run()


if __name__ == "__main__":
    main()
