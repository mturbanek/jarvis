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

import sys
import signal
import threading
import datetime

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

from config import ANTHROPIC_API_KEY, HOTKEY, OVERLAY_LINGER_MS
from overlay import JarvisOverlay
from recorder import record_voice
from stt import transcribe, prewarm as stt_prewarm
from tts import speak, stop as stop_tts
from claude import JarvisAI
from tools import set_chart_callback


class JarvisApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="ai.jarvis.desktop")
        self._processing = False
        self._greeted = False
        self._stop_event = threading.Event()
        self._startup_context = ""
        self._ai = JarvisAI()
        self.overlay: "JarvisOverlay | None" = None

    # ── GTK lifecycle ──

    def do_activate(self):
        self.overlay = JarvisOverlay(self)
        self.overlay.present()
        self.overlay.set_visible(False)

        set_chart_callback(lambda data: GLib.idle_add(self.overlay.show_chart, data))
        stt_prewarm()
        threading.Thread(target=self._hotkey_thread, daemon=True).start()
        threading.Thread(target=self._gather_startup_context, daemon=True).start()
        print(f"JARVIS ready.  Press {HOTKEY.upper()} to activate.")

    # ── startup context ──

    def _gather_startup_context(self) -> None:
        """Read shell history in the background so it's ready for the first greeting."""
        import pathlib

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

        # Deduplicate while preserving recency order
        seen: set = set()
        unique = []
        for cmd in reversed(lines[-150:]):
            if cmd not in seen:
                seen.add(cmd)
                unique.append(cmd)

        self._startup_context = "\n".join(reversed(unique[:60]))

    def _build_greeting(self, period: str) -> str:
        """Ask Claude to craft a context-aware greeting from recent shell history."""
        from anthropic import Anthropic
        from config import MODEL

        context = self._startup_context
        if not context:
            return f"Good {period}, Sir."

        try:
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
                        f"Recent shell history (most recent last):\n{context}"
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
            # Second Ctrl+J ends the session
            self._stop_event.set()
            stop_tts()
            return
        self._stop_event.clear()
        self._processing = True
        self.overlay.show_listening()
        threading.Thread(target=self._pipeline, daemon=True).start()

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
                GLib.idle_add(self.overlay.show_speaking)
                speak(greeting)

            while not self._stop_event.is_set():
                GLib.idle_add(self.overlay.show_listening)

                audio = record_voice(
                    interrupt=self._stop_event,
                    on_level=lambda rms: GLib.idle_add(self.overlay.push_audio_level, rms),
                )

                if self._stop_event.is_set():
                    break

                if audio is None:
                    # No speech within 5 seconds — close the session
                    break

                GLib.idle_add(self.overlay.show_processing)

                text = transcribe(audio)

                if self._stop_event.is_set():
                    break

                if not text:
                    continue

                GLib.idle_add(self.overlay.show_user_text, text)

                response = self._ai.process(text, on_text=on_text, on_tool=on_tool)

                if self._stop_event.is_set():
                    break

                if response:
                    GLib.idle_add(self.overlay.show_speaking)
                    speak(response)

        except Exception as exc:
            print(f"[JARVIS] Pipeline error: {exc}")

        finally:
            self._processing = False
            GLib.idle_add(self.overlay.schedule_hide, OVERLAY_LINGER_MS)


def main():
    if not ANTHROPIC_API_KEY:
        sys.exit(
            "Error: ANTHROPIC_API_KEY is not set.\n"
            "Export it before running:  export ANTHROPIC_API_KEY='sk-ant-...'"
        )

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = JarvisApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
