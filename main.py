#!/usr/bin/env python3
"""
JARVIS - AI desktop assistant for Ubuntu
Press Ctrl+J to speak. Press Ctrl+C to quit.
"""
import warnings
warnings.filterwarnings(
    "ignore",
    message="resource_tracker: There appear to be",
    category=UserWarning,
)

import math
import os
import re
import subprocess
import sys
import signal
import threading
import datetime
import json
import pathlib
from typing import Any


def _for_tts(text: str) -> str:
    """Strip markdown formatting so TTS doesn't read symbols aloud."""
    # Fenced code blocks — drop entirely (not meaningful to read aloud)
    text = re.sub(r'```[\s\S]*?```', 'code block.', text)
    # Inline code — strip backticks, keep content
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # Bold / italic markers
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'_{1,3}(.*?)_{1,3}', r'\1', text, flags=re.DOTALL)
    # ATX headers — strip # prefix
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Blockquotes
    text = re.sub(r'^>\s?', '', text, flags=re.MULTILINE)
    # Horizontal rules
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    # Links — keep display text
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    # List bullets / numbers
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+[.)]\s+', '', text, flags=re.MULTILINE)
    # Collapse excess blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def _build_activation_audio() -> "tuple[Any, int]":
    """Three quick R2-D2-style chirps: linear sweep + vibrato, subtle amplitude."""
    import numpy as np
    rate = 44100
    pi2 = 2 * math.pi

    def chirp(f0: float, f1: float, dur: float, vib_rate: float = 11.0,
              vib_depth: float = 55.0) -> "np.ndarray":
        n = int(rate * dur)
        t = np.linspace(0, dur, n, endpoint=False)
        inst_f = np.linspace(f0, f1, n) + vib_depth * np.sin(pi2 * vib_rate * t)
        phase = pi2 * np.cumsum(inst_f) / rate
        wave = np.sin(phase)
        fade = int(0.006 * rate)
        env = np.ones(n)
        env[:fade] = np.linspace(0, 1, fade)
        env[-fade:] = np.linspace(1, 0, fade)
        return wave * env

    parts = [
        chirp(900,  2400, 0.09),
        np.zeros(int(rate * 0.028)),
        chirp(2100,  750, 0.07),
        np.zeros(int(rate * 0.022)),
        chirp(1100, 1900, 0.06),
    ]
    audio = np.concatenate(parts).astype(np.float32)
    return audio * 0.46, rate


def _play_activation_sound() -> None:
    try:
        import sounddevice as sd
        audio, rate = _build_activation_audio()
        sd.play(audio, rate, device='pulse')
        sd.wait()
    except Exception as e:
        print(f"[JARVIS] Activation sound error: {e}")


def _build_done_audio() -> "tuple[Any, int]":
    """Low-high two-tone done cue: clean sine notes with natural decay."""
    import numpy as np
    rate = 44100
    pi2 = 2 * math.pi

    def tone(freq: float, dur: float, tau: float = 0.18) -> "np.ndarray":
        n = int(rate * dur)
        t = np.linspace(0, dur, n, endpoint=False)
        wave = np.sin(pi2 * freq * t)
        env = np.exp(-t / tau)
        attack = int(0.004 * rate)
        env[:attack] *= np.linspace(0, 1, attack)
        return (wave * env).astype(np.float32)

    gap = np.zeros(int(rate * 0.05), dtype=np.float32)
    audio = np.concatenate([tone(520, 0.22), gap, tone(1040, 0.28)])
    return audio * 0.52, rate


def _play_done_sound() -> None:
    try:
        import sounddevice as sd
        audio, rate = _build_done_audio()
        sd.play(audio, rate, device='pulse')
        sd.wait()
    except Exception as e:
        print(f"[JARVIS] Done sound error: {e}")


import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

from config import ANTHROPIC_API_KEY, HOTKEY, OVERLAY_LINGER_MS, MODEL
from overlay import JarvisOverlay
from recorder import record_voice
from stt import transcribe, prewarm as stt_prewarm
from tts import speak, stop as stop_tts
from claude import JarvisAI
from tools import set_chart_callback, set_speak_callback

_MEMORY_PATH = pathlib.Path.home() / ".config" / "jarvis" / "sessions.json"

_CLEAR_PHRASES = frozenset([
    "clear history", "reset history", "clear context", "reset context",
    "fresh start", "start over", "forget everything", "clear conversation",
    "reset conversation", "wipe history", "clear memory", "forget it all",
])


def _is_clear_command(text: str) -> bool:
    lower = text.lower().strip(".,!? ")
    return any(phrase in lower for phrase in _CLEAR_PHRASES)


class JarvisApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="ai.jarvis.desktop")
        self._processing = False
        self._greeted = False
        self._stop_event = threading.Event()
        self._startup_context = ""
        self._session_memory = ""
        self._ai = JarvisAI()
        self.overlay: "JarvisOverlay | None" = None
        self._tray_proc: "subprocess.Popen | None" = None

    # ── GTK lifecycle ──

    def do_activate(self):
        self.overlay = JarvisOverlay(self, on_text_submit=self._handle_text_submit)
        self.overlay.present()
        self.overlay.set_visible(False)

        set_chart_callback(lambda data: GLib.idle_add(self.overlay.show_chart, data))
        set_speak_callback(lambda text: (stop_tts(), speak(text)))

        self._session_memory = self._load_session_memory()
        if self._session_memory:
            self._ai.set_memory_context(self._session_memory)

        stt_prewarm()
        threading.Thread(target=self._hotkey_thread, daemon=True).start()
        threading.Thread(target=self._gather_startup_context, daemon=True).start()
        self._launch_tray()
        print(f"JARVIS ready.  Press {HOTKEY.upper()} to activate.")

    # ── tray icon ──

    def _launch_tray(self) -> None:
        tray_script = pathlib.Path(__file__).parent / "tray.py"
        if not tray_script.exists():
            return
        try:
            self._tray_proc = subprocess.Popen(
                [sys.executable, str(tray_script), str(os.getpid())],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # SIGUSR1 from the tray icon → behave exactly like Ctrl+J
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1,
                                 lambda: GLib.idle_add(self._trigger) or True)
        except Exception as e:
            print(f"[JARVIS] Tray icon failed to start: {e}")

    def _stop_tray(self) -> None:
        if self._tray_proc and self._tray_proc.poll() is None:
            self._tray_proc.terminate()

    # ── cross-session memory ──

    def _load_session_memory(self) -> str:
        if not _MEMORY_PATH.exists():
            return ""
        try:
            sessions = json.loads(_MEMORY_PATH.read_text())
            if not sessions:
                return ""
            lines = [f"- {s['date']}: {s['summary']}" for s in sessions[-10:]]
            return "Previous session notes:\n" + "\n".join(lines)
        except Exception:
            return ""

    def _save_session_summary(self) -> None:
        user_turns = [
            m for m in self._ai.history
            if m.get("role") == "user" and isinstance(m.get("content"), str)
        ]
        if len(user_turns) < 2:
            return
        parts = []
        for m in self._ai.history:
            role = m.get("role", "")
            content = m.get("content", "")
            if isinstance(content, str):
                parts.append(f"{role.upper()}: {content}")
            elif isinstance(content, list):
                for block in content:
                    if hasattr(block, "text"):
                        parts.append(f"{role.upper()}: {block.text}")
                        break
                    elif isinstance(block, dict) and block.get("type") == "text":
                        parts.append(f"{role.upper()}: {block.get('text', '')}")
                        break
        if not parts:
            return
        history_text = "\n".join(parts[-20:])
        try:
            from anthropic import Anthropic
            client = Anthropic()
            response = client.messages.create(
                model=MODEL,
                max_tokens=60,
                messages=[{
                    "role": "user",
                    "content": f"Summarize in one brief sentence what was discussed:\n{history_text}",
                }],
            )
            summary = response.content[0].text.strip()
            _MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            sessions = []
            if _MEMORY_PATH.exists():
                try:
                    sessions = json.loads(_MEMORY_PATH.read_text())
                except Exception:
                    pass
            sessions.append({
                "date": datetime.date.today().isoformat(),
                "summary": summary,
            })
            sessions = sessions[-20:]
            _MEMORY_PATH.write_text(json.dumps(sessions, indent=2))
        except Exception as e:
            print(f"[JARVIS] Memory save failed: {e}")

    # ── startup context ──

    def _gather_startup_context(self) -> None:
        lines = []
        for hist_path in [
            pathlib.Path.home() / ".zsh_history",
            pathlib.Path.home() / ".bash_history",
        ]:
            if not hist_path.exists():
                continue
            try:
                raw = hist_path.read_text(errors="ignore").splitlines()
                for line in raw:
                    if line.startswith(": ") and ";" in line:
                        line = line.split(";", 1)[1]
                    line = line.strip()
                    if line and not line.startswith("#"):
                        lines.append(line)
            except Exception:
                pass
            if lines:
                break

        seen: set = set()
        unique = []
        for cmd in reversed(lines[-150:]):
            if cmd not in seen:
                seen.add(cmd)
                unique.append(cmd)

        self._startup_context = "\n".join(reversed(unique[:60]))

    def _build_greeting(self, period: str) -> str:
        context_parts = []
        if self._startup_context:
            context_parts.append(f"Recent shell history (most recent last):\n{self._startup_context}")
        if self._session_memory:
            context_parts.append(self._session_memory)

        if not context_parts:
            return f"Good {period}, Sir."

        try:
            from anthropic import Anthropic
            client = Anthropic()
            response = client.messages.create(
                model=MODEL,
                max_tokens=80,
                system=(
                    "You are JARVIS, an AI desktop assistant. "
                    "Reply with exactly two short sentences. "
                    "First: greet the user as 'Sir' and mention the time of day. "
                    "Second: ask a single, specific, actionable question based on what "
                    "they were most recently working on — not a generic offer to help, "
                    "but a pointed question about their actual work (e.g. 'Shall we continue "
                    "debugging the overlay layout?' or 'Would you like to pick up the API "
                    "integration where you left off?'). Be concise and precise."
                ),
                messages=[{
                    "role": "user",
                    "content": (
                        f"Time of day: {period}.\n"
                        + "\n\n".join(context_parts)
                    ),
                }],
            )
            return response.content[0].text.strip()
        except Exception:
            return f"Good {period}, Sir."

    # ── hotkey ──

    def _hotkey_thread(self):
        import time
        import evdev
        from evdev.events import KeyEvent

        devices = []
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
                if evdev.ecodes.EV_KEY in dev.capabilities():
                    devices.append(dev)
            except Exception:
                pass

        if not devices:
            print("[JARVIS] No keyboard input devices found")
            return

        ctrl_held = set()
        ctrl_lock = threading.Lock()
        CTRL_CODES = {evdev.ecodes.KEY_LEFTCTRL, evdev.ecodes.KEY_RIGHTCTRL}

        def watch(dev):
            try:
                for event in dev.read_loop():
                    if event.type != evdev.ecodes.EV_KEY:
                        continue
                    e = evdev.categorize(event)
                    with ctrl_lock:
                        if event.code in CTRL_CODES:
                            if e.keystate == KeyEvent.key_down:
                                ctrl_held.add(event.code)
                            elif e.keystate == KeyEvent.key_up:
                                ctrl_held.discard(event.code)
                        elif (
                            event.code == evdev.ecodes.KEY_J
                            and e.keystate == KeyEvent.key_down
                            and ctrl_held
                        ):
                            GLib.idle_add(self._trigger)
            except Exception:
                pass

        for dev in devices:
            threading.Thread(target=watch, args=(dev,), daemon=True).start()

        while True:
            time.sleep(3600)

    def _trigger(self):
        if self._processing:
            self._stop_event.set()
            stop_tts()
            return
        self._stop_event.clear()
        self._processing = True
        self.overlay.disable_text_input()
        threading.Thread(target=_play_activation_sound, daemon=True).start()
        self.overlay.show_listening()
        threading.Thread(target=self._pipeline, daemon=True).start()

    # ── text-input path ──────────────────────────────────────────────────────

    def _handle_text_submit(self, text: str):
        """Called on the GTK main thread when the user submits typed input."""
        if self._processing:
            return
        if _is_clear_command(text):
            self._ai.clear_history()
            self.overlay.new_session()
            self.overlay.enable_text_input()
            return
        self._processing = True
        self.overlay.set_visible(True)
        self.overlay.show_processing()
        threading.Thread(target=self._text_pipeline, args=(text,), daemon=True).start()

    def _text_pipeline(self, text: str):
        def on_text(chunk):
            GLib.idle_add(self.overlay.append_response, chunk)
        def on_tool(name, _args):
            GLib.idle_add(self.overlay.show_tool, name)
        try:
            GLib.idle_add(self.overlay.show_user_text, text)
            response = self._ai.process(text, on_text=on_text, on_tool=on_tool)
            GLib.idle_add(self.overlay.finish_response)
            if response:
                GLib.idle_add(self.overlay.show_speaking)
                speak(_for_tts(response))
                threading.Thread(target=_play_done_sound, daemon=True).start()
        except Exception as exc:
            print(f"[JARVIS] Text pipeline error: {exc}")
        finally:
            self._processing = False
            GLib.idle_add(self.overlay.enable_text_input)
            GLib.idle_add(self.overlay.schedule_hide, OVERLAY_LINGER_MS)

    # ── voice pipeline (runs in background thread) ──

    def _pipeline(self):
        def on_text(chunk):
            GLib.idle_add(self.overlay.append_response, chunk)

        def on_tool(name, _args):
            GLib.idle_add(self.overlay.show_tool, name)

        try:
            if not self._greeted:
                self._greeted = True
                hour = datetime.datetime.now().hour
                if 5 <= hour < 12:
                    period = "Morning"
                elif 12 <= hour < 17:
                    period = "Afternoon"
                elif 17 <= hour < 21:
                    period = "Evening"
                else:
                    period = "Night"
                GLib.idle_add(self.overlay.show_processing)
                greeting = self._build_greeting(period)
                GLib.idle_add(self.overlay.add_greeting, greeting)
                GLib.idle_add(self.overlay.show_speaking)
                speak(_for_tts(greeting))

            while not self._stop_event.is_set():
                GLib.idle_add(self.overlay.show_listening)

                audio = record_voice(
                    interrupt=self._stop_event,
                    on_level=lambda rms: GLib.idle_add(self.overlay.push_audio_level, rms),
                )

                if self._stop_event.is_set():
                    break

                if audio is None:
                    break

                GLib.idle_add(self.overlay.show_processing)
                text = transcribe(audio)

                if self._stop_event.is_set():
                    break

                if not text:
                    continue

                if _is_clear_command(text):
                    self._ai.clear_history()
                    GLib.idle_add(self.overlay.new_session)
                    GLib.idle_add(self.overlay.show_speaking)
                    speak("History cleared, Sir.")  # plain text, no stripping needed
                    continue

                GLib.idle_add(self.overlay.show_user_text, text)

                response = self._ai.process(text, on_text=on_text, on_tool=on_tool)
                GLib.idle_add(self.overlay.finish_response)

                if self._stop_event.is_set():
                    break

                if response:
                    GLib.idle_add(self.overlay.show_speaking)
                    speak(_for_tts(response))
                    threading.Thread(target=_play_done_sound, daemon=True).start()

        except Exception as exc:
            print(f"[JARVIS] Pipeline error: {exc}")

        finally:
            self._processing = False
            threading.Thread(target=self._save_session_summary, daemon=True).start()
            GLib.idle_add(self.overlay.enable_text_input)
            GLib.idle_add(self.overlay.schedule_hide, OVERLAY_LINGER_MS)


def main():
    if not ANTHROPIC_API_KEY:
        sys.exit(
            "Error: ANTHROPIC_API_KEY is not set.\n"
            "Export it before running:  export ANTHROPIC_API_KEY='sk-ant-...'"
        )

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = JarvisApp()
    try:
        return app.run(sys.argv)
    finally:
        app._stop_tray()


if __name__ == "__main__":
    sys.exit(main())
