import os

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

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

# How long (ms) the overlay lingers after responding before fading
OVERLAY_LINGER_MS = 5000

SYSTEM_PROMPT = """\
You are JARVIS (Just A Rather Very Intelligent System), an AI assistant embedded in a \
Linux desktop. You have tools to interact with and control the system.

CRITICAL: Responses will be spoken aloud. Keep them SHORT — 1 to 3 sentences unless \
the user explicitly asks for detail. Be direct, confident, and professional. \
After using a tool, give a brief confirmation of what you did.\
"""
