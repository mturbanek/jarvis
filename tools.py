import json
import os
import pathlib
import subprocess
import datetime
import threading
import time
from collections import deque

import psutil

# ── Performance sampler ───────────────────────────────────────────────────────

_HISTORY = 60  # ~2 minutes at 2 s intervals
_perf_cpu: deque = deque([0.0] * _HISTORY, maxlen=_HISTORY)
_perf_ram: deque = deque([0.0] * _HISTORY, maxlen=_HISTORY)


def _perf_sampler() -> None:
    psutil.cpu_percent()  # prime — first call always returns 0.0
    while True:
        time.sleep(2.0)
        _perf_cpu.append(psutil.cpu_percent())
        _perf_ram.append(psutil.virtual_memory().percent)


threading.Thread(target=_perf_sampler, daemon=True, name="perf-sampler").start()

# ── Chart callback ────────────────────────────────────────────────────────────

_chart_callback = None


def set_chart_callback(cb) -> None:
    global _chart_callback
    _chart_callback = cb


# ── Timer management ──────────────────────────────────────────────────────────

_timers: dict = {}  # label -> (threading.Timer, end_timestamp)
_timer_lock = threading.Lock()
_speak_callback = None


def set_speak_callback(cb) -> None:
    global _speak_callback
    _speak_callback = cb


def _fire_timer(label: str) -> None:
    with _timer_lock:
        _timers.pop(label, None)
    msg = (
        f"Sir, your {label} timer has expired."
        if label != "timer"
        else "Sir, your timer has expired."
    )
    subprocess.run(["notify-send", "JARVIS Timer", msg, "--icon=alarm"], check=False)
    if _speak_callback:
        _speak_callback(msg)


# ── Tool definitions ──────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "run_shell",
        "description": (
            "Execute a shell command and return its output. Use for file operations, "
            "querying system state, running scripts, or anything that needs a terminal."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"}
            },
            "required": ["command"],
        },
    },
    {
        "name": "open_application",
        "description": "Launch a desktop application by its executable name (e.g. 'firefox', 'gnome-terminal', 'code', 'nautilus').",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Executable name or command to launch"}
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_system_info",
        "description": "Return current CPU usage, RAM usage, disk space, and system uptime.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_datetime",
        "description": "Return the current date and time.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "send_notification",
        "description": "Send a desktop notification pop-up to the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["title", "message"],
        },
    },
    {
        "name": "get_clipboard",
        "description": "Read the current clipboard contents.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "set_clipboard",
        "description": "Write text to the clipboard.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to place on the clipboard"}
            },
            "required": ["text"],
        },
    },
    {
        "name": "get_performance_history",
        "description": (
            "Return CPU and RAM usage sampled every 2 seconds over the last ~2 minutes. "
            "The result is a JSON object already formatted for show_chart (type=line). "
            "Call show_chart with the parsed result to display the trend."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "show_chart",
        "description": (
            "Display a chart in the Jarvis overlay. "
            "type='line': time-series — needs 'series' (list of {name, values}) and 'labels'. "
            "type='bar': comparisons — same format as line. "
            "type='donut': proportions — needs 'labels' and 'values' (one number per label). "
            "Always include a 'title'. Pass get_performance_history output directly for perf charts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "type":   {"type": "string", "enum": ["line", "bar", "donut"]},
                "title":  {"type": "string"},
                "labels": {"type": "array", "items": {"type": "string"}},
                "series": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name":   {"type": "string"},
                            "values": {"type": "array", "items": {"type": "number"}},
                        },
                    },
                },
                "values": {"type": "array", "items": {"type": "number"}},
            },
            "required": ["type", "title"],
        },
    },
    {
        "name": "set_timer",
        "description": (
            "Set a countdown timer. When it expires JARVIS will announce it aloud "
            "and send a desktop notification."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "integer",
                    "description": "Duration in seconds (e.g. 300 for 5 minutes)",
                },
                "label": {
                    "type": "string",
                    "description": "What the timer is for (e.g. 'pasta', 'standup', 'focus block'). Defaults to 'timer'.",
                },
            },
            "required": ["seconds"],
        },
    },
    {
        "name": "cancel_timer",
        "description": "Cancel a running timer by its label.",
        "input_schema": {
            "type": "object",
            "properties": {
                "label": {"type": "string", "description": "Label of the timer to cancel"},
            },
            "required": ["label"],
        },
    },
    {
        "name": "list_timers",
        "description": "List all active timers and their remaining time.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_weather",
        "description": (
            "Get current weather conditions for a location. "
            "Provide a city name or leave blank to use the system's detected location."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City name (e.g. 'London', 'Tokyo', 'New York'). Omit to auto-detect.",
                }
            },
        },
    },
    {
        "name": "find_and_open",
        "description": (
            "Search for files by name pattern in the filesystem. "
            "Optionally open the first match with its default desktop application."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Filename glob pattern (e.g. '*.pdf', 'report*', 'resume.docx')",
                },
                "directory": {
                    "type": "string",
                    "description": "Directory to search in. Defaults to the user's home directory.",
                },
                "open": {
                    "type": "boolean",
                    "description": "If true, open the first matching file with xdg-open.",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum directory depth to search (default 5).",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "read_screen",
        "description": (
            "Take a screenshot of the current screen and extract all visible text using OCR. "
            "Useful for reading error messages, dialog boxes, terminal output, or any on-screen text."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


# ── Tool executor ─────────────────────────────────────────────────────────────

def execute_tool(name: str, args: dict) -> str:
    try:
        if name == "run_shell":
            result = subprocess.run(
                args["command"], shell=True, capture_output=True, text=True, timeout=30
            )
            output = (result.stdout + result.stderr).strip() or "(no output)"
            return output[:2000]

        elif name == "open_application":
            subprocess.Popen(
                [args["name"]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return f"Launched {args['name']}"

        elif name == "get_system_info":
            cpu = _perf_cpu[-1]
            ram = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            boot = datetime.datetime.fromtimestamp(psutil.boot_time())
            uptime = datetime.datetime.now() - boot
            h, rem = divmod(int(uptime.total_seconds()), 3600)
            m = rem // 60
            return (
                f"CPU {cpu:.1f}% | "
                f"RAM {ram.percent}% ({ram.used // 1024**3}/{ram.total // 1024**3} GB) | "
                f"Disk {disk.percent}% | "
                f"Uptime {h}h {m}m"
            )

        elif name == "get_datetime":
            return datetime.datetime.now().strftime("%A, %B %-d %Y at %-I:%M %p")

        elif name == "send_notification":
            subprocess.run(
                ["notify-send", args["title"], args.get("message", ""), "--icon=dialog-information"],
                check=False,
            )
            return "Notification sent"

        elif name == "get_clipboard":
            for cmd in [["wl-paste", "--no-newline"], ["xclip", "-selection", "clipboard", "-o"]]:
                r = subprocess.run(cmd, capture_output=True, text=True)
                if r.returncode == 0:
                    return r.stdout.strip() or "(empty)"
            return "(could not read clipboard)"

        elif name == "set_clipboard":
            text = args["text"]
            for cmd, stdin_text in [
                (["wl-copy"], text),
                (["xclip", "-selection", "clipboard"], text),
            ]:
                r = subprocess.run(cmd, input=stdin_text, text=True, capture_output=True)
                if r.returncode == 0:
                    return "Copied to clipboard"
            return "Could not write to clipboard"

        elif name == "get_performance_history":
            cpu = list(_perf_cpu)
            ram = list(_perf_ram)
            n = len(cpu)
            labels = [f"-{(n - 1 - i) * 2}s" for i in range(n)]
            return json.dumps({
                "type": "line",
                "title": "System Performance",
                "labels": labels,
                "series": [
                    {"name": "CPU %", "values": cpu},
                    {"name": "RAM %", "values": ram},
                ],
            })

        elif name == "show_chart":
            if _chart_callback:
                _chart_callback(args)
                return "Chart displayed in overlay."
            return "Chart display not available."

        elif name == "set_timer":
            seconds = int(args["seconds"])
            label = args.get("label", "timer")
            with _timer_lock:
                if label in _timers:
                    _timers[label][0].cancel()
                t = threading.Timer(seconds, _fire_timer, args=[label])
                t.daemon = True
                t.start()
                _timers[label] = (t, time.time() + seconds)
            mins, secs = divmod(seconds, 60)
            dur = f"{mins}m {secs}s" if mins else f"{secs}s"
            return f"Timer '{label}' set for {dur}."

        elif name == "cancel_timer":
            label = args["label"]
            with _timer_lock:
                entry = _timers.pop(label, None)
            if entry:
                entry[0].cancel()
                return f"Timer '{label}' cancelled."
            return f"No active timer named '{label}'."

        elif name == "list_timers":
            with _timer_lock:
                if not _timers:
                    return "No active timers."
                now = time.time()
                lines = []
                for label, (_, end_time) in _timers.items():
                    remaining = max(0, int(end_time - now))
                    mins, secs = divmod(remaining, 60)
                    lines.append(
                        f"'{label}': {mins}m {secs}s remaining"
                        if mins
                        else f"'{label}': {secs}s remaining"
                    )
                return "\n".join(lines)

        elif name == "get_weather":
            location = args.get("location", "")
            url = (
                f"https://wttr.in/{location}?format=j1"
                if location
                else "https://wttr.in/?format=j1"
            )
            result = subprocess.run(
                ["curl", "-s", "--max-time", "10", url],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return "Could not fetch weather data. Check your internet connection."
            try:
                data = json.loads(result.stdout)
                current = data["current_condition"][0]
                area = data["nearest_area"][0]
                location_name = area["areaName"][0]["value"]
                country = area["country"][0]["value"]
                temp_c = current["temp_C"]
                feels_c = current["FeelsLikeC"]
                desc = current["weatherDesc"][0]["value"]
                humidity = current["humidity"]
                wind_kmph = current["windspeedKmph"]
                return (
                    f"{location_name}, {country}: {desc}. "
                    f"{temp_c}°C (feels like {feels_c}°C). "
                    f"Humidity {humidity}%, wind {wind_kmph} km/h."
                )
            except (KeyError, json.JSONDecodeError) as e:
                return f"Could not parse weather data: {e}"

        elif name == "find_and_open":
            pattern = args["pattern"]
            directory = args.get("directory", str(pathlib.Path.home()))
            max_depth = args.get("max_depth", 5)
            should_open = args.get("open", False)

            result = subprocess.run(
                [
                    "find", directory,
                    "-maxdepth", str(max_depth),
                    "-name", pattern,
                    "-type", "f",
                    "-not", "-path", "*/.*",
                ],
                capture_output=True, text=True, timeout=20,
            )
            files = [f for f in result.stdout.strip().splitlines() if f]
            if not files:
                return f"No files matching '{pattern}' found in {directory}."

            if should_open:
                subprocess.Popen(
                    ["xdg-open", files[0]],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                suffix = f"\n\nAll matches ({len(files)}):\n" + "\n".join(files[:10])
                return f"Opening {files[0]}." + suffix

            shown = files[:20]
            more = f"\n… and {len(files) - 20} more" if len(files) > 20 else ""
            return f"Found {len(files)} file(s):\n" + "\n".join(shown) + more

        elif name == "read_screen":
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                screenshot = os.path.join(tmp, "screen.png")
                captured = False
                for cmd in [["grim", screenshot], ["scrot", screenshot]]:
                    r = subprocess.run(cmd, capture_output=True)
                    if r.returncode == 0:
                        captured = True
                        break
                if not captured:
                    return (
                        "Could not take a screenshot. "
                        "Install grim (Wayland): sudo apt install grim  "
                        "or scrot (X11): sudo apt install scrot"
                    )
                r = subprocess.run(
                    ["tesseract", screenshot, "stdout"],
                    capture_output=True, text=True,
                )
                if r.returncode != 0:
                    return "OCR failed. Install tesseract: sudo apt install tesseract-ocr"
                text = r.stdout.strip()
                return text[:3000] if text else "(no text found on screen)"

        else:
            return f"Unknown tool: {name}"

    except subprocess.TimeoutExpired:
        return "Command timed out"
    except FileNotFoundError as e:
        return f"Command not found: {e.filename}"
    except Exception as e:
        return f"Tool error: {e}"
