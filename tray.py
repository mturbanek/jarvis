#!/usr/bin/env python3
"""
JARVIS system tray icon.
Runs as a subprocess (GTK3 + AyatanaAppIndicator3) so it doesn't conflict
with the main GTK4 app. Communicates via OS signals:
  SIGUSR1 → main process  (toggle show/hide / activate)
  SIGTERM → main process  (quit)
Usage: python3 tray.py <main_pid>
"""
import os
import signal
import sys

import gi
gi.require_version("AyatanaAppIndicator3", "0.1")
gi.require_version("Gtk", "3.0")
from gi.repository import AyatanaAppIndicator3, Gtk

_MAIN_PID = int(sys.argv[1]) if len(sys.argv) > 1 else None


def _send(sig: int) -> None:
    if _MAIN_PID:
        try:
            os.kill(_MAIN_PID, sig)
        except ProcessLookupError:
            Gtk.main_quit()


def _on_toggle(_item=None) -> None:
    _send(signal.SIGUSR1)


def _on_quit(_item=None) -> None:
    _send(signal.SIGTERM)
    Gtk.main_quit()


# --- menu ---
menu = Gtk.Menu()

item_activate = Gtk.MenuItem(label="Activate JARVIS  (Ctrl+J)")
item_activate.connect("activate", _on_toggle)
menu.append(item_activate)

menu.append(Gtk.SeparatorMenuItem())

item_quit = Gtk.MenuItem(label="Quit")
item_quit.connect("activate", _on_quit)
menu.append(item_quit)

menu.show_all()

# --- indicator ---
indicator = AyatanaAppIndicator3.Indicator.new(
    "jarvis-tray",
    "audio-input-microphone",
    AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS,
)
indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
indicator.set_title("JARVIS")
indicator.set_menu(menu)

# Exit cleanly if the main process dies
signal.signal(signal.SIGTERM, lambda *_: Gtk.main_quit())

Gtk.main()
