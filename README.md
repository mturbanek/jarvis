# JARVIS

A voice-activated AI desktop assistant for Linux (Wayland/X11), powered by Claude.

Press **Ctrl+J** to start a voice session, or type directly into the overlay text box. JARVIS greets you with a context-aware message based on your recent shell history, then listens continuously until you stop talking or press Ctrl+J again.

---

## Features

- **Continuous conversation** — one Ctrl+J starts a full back-and-forth session; no need to press it between turns
- **Cross-session memory** — JARVIS summarises each conversation and recalls it in future sessions
- **Real-time audio waveform** — the overlay visualises your voice as you speak
- **Personalised greeting** — analyses your shell history and past sessions to ask a pointed question about what you were last working on
- **Tool use** — Claude can run shell commands, open apps, set timers, check weather, find files, and more
- **Charts** — ask JARVIS to graph CPU/RAM trends, disk usage, git stats, or any data it can access
- **State-based UI** — overlay accent colour shifts per state (blue → listening, amber → processing, cyan → responding, purple → speaking)
- **Scrollable conversation history** — full back-and-forth transcript with per-turn timestamps; persists across Ctrl+J presses until you say "clear history"
- **Typing cursor** — blinking cursor animates while JARVIS streams a response, stops when done
- **Scan lines + particle field** — subtle CRT scan-line overlay and drifting star-field for ambiance
- **R2-D2 activation sound** — three quick swept chirps play on Ctrl+J
- **Draggable + resizable window** — drag by the header, resize from the bottom-right grip
- **Vision screen reading** — `read_screen` uses Claude's vision API instead of OCR; can describe UI, interpret charts, and answer specific questions about screen content
- **Typed input** — text box at the bottom of the overlay; always available when JARVIS isn't actively listening, so you can follow up without speaking
- **Done sound** — low-high two-tone chime plays after each response so you know it's your turn
- **GNOME launcher** — `.desktop` file for the app grid/dock; tray icon in the top bar (requires AppIndicator GNOME extension) with Activate and Quit menu items
- **Persistent overlay** — the panel stays visible; no auto-hide or fade-out
- **5-second silence timeout** — voice session ends automatically if you stop talking

---

## Requirements

- Ubuntu 24.04+ (or any distro with GTK4 and Python 3.10+)
- Wayland or X11
- `mpv` (audio playback)
- An [Anthropic API key](https://console.anthropic.com/)
- Your user in the `input` group (for Wayland hotkey support)
- `flameshot` (optional — required for the `read_screen` tool; `grim` works on wlroots compositors)

---

## Installation

```bash
# 1. Clone
git clone https://github.com/mturbanek/jarvis.git
cd jarvis

# 2. Run setup (installs system packages + Python venv)
chmod +x setup.sh
./setup.sh

# 3. Add yourself to the input group (Wayland hotkey — requires re-login)
sudo usermod -aG input $USER
```

---

## Usage

```bash
export ANTHROPIC_API_KEY='sk-ant-...'
./venv/bin/python main.py
```

Or store the key in `~/.config/jarvis/env` (one line: `ANTHROPIC_API_KEY=sk-ant-...`) and launch from the GNOME dock or app grid.

| Action | Effect |
|---|---|
| **Ctrl+J** | Start voice session (greeting + continuous listening) |
| **Ctrl+J** (during session) | End session immediately |
| Silence for 5 seconds | Session closes automatically |
| Type + **Enter** in text box | Send a message without using voice |
| *"Clear history"* / *"Fresh start"* | Wipe the current session's conversation history |

---

## Configuration

All tunable settings are in `config.py`:

| Setting | Default | Description |
|---|---|---|
| `MODEL` | `claude-haiku-4-5` | Claude model (`haiku` = fastest, `sonnet` = balanced, `opus` = smartest) |
| `WHISPER_MODEL` | `base` | Whisper STT size (`tiny` → `base` → `small` → `medium`) |
| `TTS_VOICE` | `en-GB-RyanNeural` | Edge TTS voice |
| `HOTKEY` | `<ctrl>+j` | Global trigger key |

---

## Available Tools

| Tool | What it does |
|---|---|
| `run_shell` | Execute any shell command |
| `open_application` | Launch a desktop app |
| `get_system_info` | Current CPU, RAM, disk, uptime |
| `get_datetime` | Current date and time |
| `send_notification` | Desktop notification pop-up |
| `get_clipboard` / `set_clipboard` | Read or write clipboard |
| `get_performance_history` | 2 minutes of CPU + RAM samples |
| `show_chart` | Render a line, bar, or donut chart in the overlay |
| `set_timer` / `cancel_timer` / `list_timers` | Voice-announced countdown timers |
| `get_weather` | Current weather for any city (no API key needed) |
| `find_and_open` | Search files by name pattern, optionally open the match |
| `read_screen` | Screenshot + Claude vision — describe UI, read text, interpret charts; accepts an optional `query` |
| `add_note` | Save a timestamped note to `~/notes.md` |
| `read_notes` | Read your most recent notes |
| `search_notes` | Search notes by keyword |

### Example requests

- *"Set a 25-minute focus timer"*
- *"What's the weather in Tokyo?"*
- *"Find my resume and open it"*
- *"What does that error message say?"* — JARVIS reads the screen
- *"Note that the deploy key needs rotating next week"*
- *"What did I note about the API?"*
- *"Show me CPU and RAM over the last two minutes"*
- *"Graph disk usage by partition"*

---

## Architecture

```
main.py       GTK app, hotkey listener, voice + text pipelines, greeting, tray launch
overlay.py    Transparent GTK4 window — waveform, chat log, text entry, state transitions
tray.py       GTK3 subprocess — AyatanaAppIndicator3 tray icon, signals main via SIGUSR1
recorder.py   Mic capture (sounddevice) with VAD and silence timeout
stt.py        Whisper transcription via faster-whisper (CPU int8)
tts.py        edge-tts synthesis → mpv playback
claude.py     Anthropic streaming client with conversation history
tools.py      Tool definitions, executor, background performance sampler
config.py     Constants and tunables; reads API key from ~/.config/jarvis/env as fallback
```
