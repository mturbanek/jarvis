#!/usr/bin/env bash
# JARVIS setup script for Ubuntu 24.04+ / 26.04
set -e

echo "=== JARVIS Setup ==="

echo
echo "► Installing system packages..."
sudo apt update -qq
sudo apt install -y \
    python3-gi \
    python3-gi-cairo \
    gir1.2-gtk-4.0 \
    python3-venv \
    python3-pip \
    portaudio19-dev \
    libportaudio2 \
    mpv \
    xclip \
    libnotify-bin \
    curl \
    tesseract-ocr \
    flameshot

# gtk4-layer-shell gives proper bottom-anchored Wayland overlay (optional)
echo
echo "► Trying to install grim (optional, for non-GNOME Wayland compositors)..."
sudo apt install -y grim 2>/dev/null \
    || echo "  (grim not available — flameshot will be used on GNOME Wayland)"

echo
echo "► Trying to install gtk4-layer-shell (optional, Wayland overlay)..."
sudo apt install -y gir1.2-gtk4layershell-1.0 2>/dev/null \
    || sudo apt install -y gir1.2-gtklayershell-0.1 2>/dev/null \
    || echo "  (gtk4-layer-shell not available — overlay will appear centred instead)"

echo
echo "► Creating Python virtual environment with system packages access..."
python3 -m venv venv --system-site-packages

echo
echo "► Installing Python packages..."
./venv/bin/pip install --quiet -r requirements.txt

echo
echo "=== Done! ==="
echo
echo "Set your API key and launch:"
echo "  export ANTHROPIC_API_KEY='sk-ant-...'"
echo "  ./venv/bin/python main.py"
echo
echo "Then press Ctrl+J anywhere on your desktop to talk to JARVIS."
echo
echo "NOTE: If the hotkey doesn't work under Wayland, either:"
echo "  • Switch to 'GNOME on X11' at the login screen, or"
echo "  • Add yourself to the 'input' group:  sudo usermod -aG input \$USER"
echo "    (then log out and back in)"
