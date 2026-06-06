#!/usr/bin/env bash
# Launch JARVIS from the GNOME desktop or terminal.
# API key is read from ~/.config/jarvis/env (set ANTHROPIC_API_KEY=sk-ant-...)
cd "$(dirname "$0")"
exec ./venv/bin/python main.py "$@"
