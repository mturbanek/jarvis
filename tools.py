import json
import subprocess
import datetime
import threading
import time
from collections import deque

import psutil

# ── Performance sampler ───────────────────────────────────────────────────────
# Samples CPU and RAM every 2 s in the background.
# get_system_info and get_performance_history read from this buffer instantly.

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

        else:
            return f"Unknown tool: {name}"

    except subprocess.TimeoutExpired:
        return "Command timed out after 30 seconds"
    except FileNotFoundError as e:
        return f"Command not found: {e.filename}"
    except Exception as e:
        return f"Tool error: {e}"
