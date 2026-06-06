# JARVIS

A voice-activated AI desktop assistant for Linux (Wayland/X11), powered by Claude.

Press **Ctrl+J** to start a session. JARVIS greets you with a context-aware message based on your recent shell history, then listens continuously until you stop talking or press Ctrl+J again.

---

## Features

- **Continuous conversation** — one Ctrl+J starts a full back-and-forth session; no need to press it between turns
- **Real-time audio waveform** — the overlay visualises your voice as you speak
- **Personalised greeting** — analyses your shell history to ask a pointed question about what you were last working on
- **Tool use** — Claude can run shell commands, open apps, read/write clipboard, send notifications, and more
- **Charts** — ask JARVIS to graph CPU/RAM trends, disk usage, git stats, or any data it can access
- **State-based UI** — overlay accent colour shifts per state (blue → listening, amber → processing, cyan → responding, purple → speaking)
- **5-second silence timeout** — session closes automatically if you stop talking

---

## Requirements

- Ubuntu 24.04+ (or any distro with GTK4 and Python 3.10+)
- Wayland or X11
- `mpv` (audio playback)
- An [Anthropic API key](https://console.anthropic.com/)
- Your user in the `input` group (for Wayland hotkey support)

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

| Action | Effect |
|---|---|
| **Ctrl+J** | Start session (greeting + continuous listening) |
| **Ctrl+J** (during session) | End session immediately |
| Silence for 5 seconds | Session closes automatically |

---

## Configuration

All tunable settings are in `config.py`:

| Setting | Default | Description |
|---|---|---|
| `MODEL` | `claude-haiku-4-5` | Claude model (`haiku` = fastest, `sonnet` = balanced, `opus` = smartest) |
| `WHISPER_MODEL` | `base` | Whisper STT size (`tiny` → `base` → `small` → `medium`) |
| `TTS_VOICE` | `en-GB-RyanNeural` | Edge TTS voice |
| `HOTKEY` | `<ctrl>+j` | Global trigger key |
| `OVERLAY_LINGER_MS` | `5000` | How long the overlay stays visible after a response |

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

### Example chart requests

- *"Show me CPU and RAM over the last two minutes"*
- *"Graph disk usage by partition"*
- *"Chart the biggest directories in my home folder"*

---

## Architecture

```
main.py       GTK app, evdev hotkey listener, session loop, greeting
overlay.py    Transparent GTK4 window — waveform, charts, state transitions
recorder.py   Mic capture (sounddevice) with VAD and silence timeout
stt.py        Whisper transcription via faster-whisper (CPU int8)
tts.py        edge-tts synthesis → mpv playback
claude.py     Anthropic streaming client with conversation history
tools.py      Tool definitions, executor, background performance sampler
config.py     Constants and tunables
```
