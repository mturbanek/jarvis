import os
import pathlib

# Read API key from env var, falling back to ~/.config/jarvis/env so the app
# works when launched from the GNOME desktop (which doesn't source .bashrc).
def _load_api_key() -> str:
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if key:
        return key
    env_file = pathlib.Path.home() / ".config" / "jarvis" / "env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""

ANTHROPIC_API_KEY = _load_api_key()

# claude-haiku-4-5 = fastest voice responses (~1s)
# claude-sonnet-4-6 = balanced speed + smarts
# claude-opus-4-8   = smartest, slowest (~3-5s)
MODEL = "claude-haiku-4-5"

# Whisper STT model: tiny (fastest) → base → small → medium (best accuracy)
WHISPER_MODEL = "base"

# TTS voice via Microsoft Neural (requires internet)
# British: en-GB-RyanNeural, en-GB-SoniaNeural
# American: en-US-GuyNeural, en-US-JennyNeural
TTS_VOICE = "en-GB-RyanNeural"

# Global hotkey to trigger Jarvis
HOTKEY = "<ctrl>+j"


SYSTEM_PROMPT = """\
You are JARVIS (Just A Rather Very Intelligent System), an AI assistant embedded in a \
Linux desktop. You have tools to interact with and control the system.

CRITICAL: Responses will be spoken aloud. Keep them SHORT — 1 to 3 sentences unless \
the user explicitly asks for detail. Be direct, confident, and professional. \
After using a tool, give a brief confirmation of what you did.\
"""
