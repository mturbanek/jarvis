import math
from collections import deque
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib

_LAYER_SHELL = False
try:
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell as _ls
    _LAYER_SHELL = True
except (ValueError, ImportError):
    _ls = None

_STATE_COLORS = {
    "idle":       (0.20, 0.52, 1.00),
    "listening":  (0.20, 0.52, 1.00),
    "processing": (1.00, 0.70, 0.12),
    "responding": (0.08, 0.82, 0.92),
    "speaking":   (0.65, 0.35, 1.00),
}

_CSS = b"""
window.jarvis-root {
    background-color: transparent;
}

.jarvis-panel {
    background: linear-gradient(150deg, rgba(5,12,32,0.97) 0%, rgba(3,7,18,0.99) 100%);
    border: 1px solid rgba(52, 140, 255, 0.40);
    border-top: 2px solid rgba(52, 140, 255, 0.60);
    border-radius: 24px;
    padding: 22px 32px 26px 32px;
    box-shadow:
        0 20px 56px rgba(0,0,0,0.80),
        inset 0 1px 0 rgba(255,255,255,0.06);
}

.state-listening {
    border-color: rgba(52, 140, 255, 0.88);
    border-top-color: rgba(80, 170, 255, 0.95);
    box-shadow:
        0 20px 56px rgba(0,0,0,0.80),
        0 0 52px rgba(52, 140, 255, 0.34),
        0 0 104px rgba(52, 140, 255, 0.14),
        inset 0 1px 0 rgba(255,255,255,0.08);
}

.state-processing {
    border-color: rgba(255, 178, 30, 0.88);
    border-top-color: rgba(255, 210, 80, 0.95);
    box-shadow:
        0 20px 56px rgba(0,0,0,0.80),
        0 0 52px rgba(255, 178, 30, 0.32),
        0 0 104px rgba(255, 178, 30, 0.12),
        inset 0 1px 0 rgba(255,255,255,0.08);
}

.state-responding {
    border-color: rgba(20, 215, 245, 0.88);
    border-top-color: rgba(60, 240, 255, 0.95);
    box-shadow:
        0 20px 56px rgba(0,0,0,0.80),
        0 0 52px rgba(20, 215, 245, 0.32),
        0 0 104px rgba(20, 215, 245, 0.12),
        inset 0 1px 0 rgba(255,255,255,0.08);
}

.state-speaking {
    border-color: rgba(165, 82, 255, 0.88);
    border-top-color: rgba(200, 125, 255, 0.95);
    box-shadow:
        0 20px 56px rgba(0,0,0,0.80),
        0 0 52px rgba(165, 82, 255, 0.32),
        0 0 104px rgba(165, 82, 255, 0.12),
        inset 0 1px 0 rgba(255,255,255,0.08);
}

.title-label {
    color: #6aadff;
    font-family: monospace;
    font-size: 20px;
    font-weight: bold;
    letter-spacing: 8px;
}

.status-label {
    color: rgba(100, 160, 255, 0.80);
    font-family: monospace;
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 3px;
}

.header-sep {
    background: linear-gradient(90deg, transparent, rgba(52, 120, 255, 0.22), transparent);
    min-height: 1px;
    margin-top: 4px;
    margin-bottom: 0px;
}

.user-label {
    color: rgba(130, 175, 255, 0.65);
    font-family: sans-serif;
    font-size: 14px;
    font-style: italic;
    margin-bottom: 4px;
}

.response-label {
    color: rgba(235, 245, 255, 0.97);
    font-family: sans-serif;
    font-size: 18px;
}

.turn-sep {
    background: linear-gradient(90deg, transparent, rgba(52, 120, 255, 0.16), transparent);
    min-height: 1px;
    margin-top: 18px;
    margin-bottom: 18px;
}

.divider {
    background-color: rgba(52, 120, 255, 0.18);
    min-height: 1px;
    margin-top: 10px;
    margin-bottom: 10px;
}

scrollbar {
    background: rgba(255, 255, 255, 0.04);
    border-radius: 4px;
}
scrollbar slider {
    background: rgba(100, 160, 255, 0.45);
    min-width: 7px;
    min-height: 20px;
    border-radius: 4px;
    margin: 2px;
}
scrollbar slider:hover {
    background: rgba(100, 160, 255, 0.80);
}
"""

_ALL_STATES = ("idle", "listening", "processing", "responding", "speaking")

_CHART_COLORS = [
    (0.20, 0.52, 1.00),
    (0.08, 0.82, 0.92),
    (0.65, 0.35, 1.00),
    (1.00, 0.70, 0.12),
    (0.20, 0.85, 0.55),
    (1.00, 0.35, 0.40),
]


class _ChartWidget(Gtk.DrawingArea):
    """Cairo chart renderer — line, bar, or donut."""

    _H_CHART = 190
    _H_DONUT = 215

    def __init__(self):
        super().__init__()
        self.set_hexpand(True)
        self.set_draw_func(self._draw)
        self._data: "dict | None" = None

    def load(self, data: dict) -> None:
        self._data = data
        h = self._H_DONUT if data.get("type") == "donut" else self._H_CHART
        self.set_content_height(h)
        self.queue_draw()

    def clear(self) -> None:
        self._data = None
        self.queue_draw()

    def _draw(self, _widget, cr, w, h):
        if not self._data:
            return
        t = self._data.get("type", "bar")
        if t == "line":
            self._line(cr, w, h)
        elif t == "bar":
            self._bar(cr, w, h)
        elif t == "donut":
            self._donut(cr, w, h)

    @staticmethod
    def _font(cr, size: float, bold: bool = False) -> None:
        cr.select_font_face("monospace", 0, 1 if bold else 0)
        cr.set_font_size(size)

    @staticmethod
    def _axes(cr, pl, pt, pw, ph) -> None:
        cr.set_source_rgba(1, 1, 1, 0.12)
        cr.set_line_width(1)
        cr.move_to(pl, pt)
        cr.line_to(pl, pt + ph)
        cr.line_to(pl + pw, pt + ph)
        cr.stroke()

    @staticmethod
    def _grid(cr, pl, pt, pw, ph, vmin, vmax) -> None:
        vspan = vmax - vmin
        for i in range(5):
            frac = i / 4
            y = pt + frac * ph
            v = vmax - frac * vspan
            cr.set_source_rgba(1, 1, 1, 0.05)
            cr.set_line_width(0.5)
            cr.move_to(pl, y)
            cr.line_to(pl + pw, y)
            cr.stroke()
            cr.set_source_rgba(0.55, 0.75, 1.0, 0.55)
            _ChartWidget._font(cr, 8)
            cr.move_to(2, y + 4)
            cr.show_text(f"{v:.0f}")

    def _line(self, cr, w, h):
        d = self._data
        series_list = d.get("series", [])
        labels = d.get("labels", [])
        title = d.get("title", "")

        PL, PR, PT, PB = 44, 16, 26, 30
        pw, ph = w - PL - PR, h - PT - PB

        all_vals = [v for s in series_list for v in s.get("values", [])]
        if not all_vals:
            return
        vmin, vmax = min(all_vals), max(all_vals)
        if vmax == vmin:
            vmax = vmin + 1
        vspan = vmax - vmin

        n_pts = max((len(s.get("values", [])) for s in series_list), default=1)
        def gx(i): return PL + (i / max(n_pts - 1, 1)) * pw
        def gy(v): return PT + (1 - (v - vmin) / vspan) * ph

        if title:
            cr.set_source_rgba(0.75, 0.88, 1.0, 0.85)
            self._font(cr, 11, bold=True)
            cr.move_to(PL, 18)
            cr.show_text(title)

        self._grid(cr, PL, PT, pw, ph, vmin, vmax)
        self._axes(cr, PL, PT, pw, ph)

        for si, s in enumerate(series_list):
            vals = s.get("values", [])
            if not vals:
                continue
            r, g, b = _CHART_COLORS[si % len(_CHART_COLORS)]

            cr.set_source_rgba(r, g, b, 0.09)
            cr.move_to(gx(0), PT + ph)
            cr.line_to(gx(0), gy(vals[0]))
            for i, v in enumerate(vals[1:], 1):
                cr.line_to(gx(i), gy(v))
            cr.line_to(gx(len(vals) - 1), PT + ph)
            cr.close_path()
            cr.fill()

            cr.set_source_rgba(r, g, b, 0.90)
            cr.set_line_width(1.5)
            cr.move_to(gx(0), gy(vals[0]))
            for i, v in enumerate(vals[1:], 1):
                cr.line_to(gx(i), gy(v))
            cr.stroke()

            lx = PL + pw - 90
            ly = 8 + si * 14
            cr.set_source_rgba(r, g, b, 0.9)
            cr.rectangle(lx, ly - 5, 10, 7)
            cr.fill()
            cr.set_source_rgba(0.72, 0.86, 1.0, 0.75)
            self._font(cr, 9)
            cr.move_to(lx + 13, ly + 1)
            cr.show_text(s.get("name", f"S{si + 1}"))

        if labels:
            step = max(1, len(labels) // 7)
            cr.set_source_rgba(0.55, 0.75, 1.0, 0.55)
            self._font(cr, 8)
            for i in range(0, len(labels), step):
                cr.move_to(gx(i) - 6, PT + ph + 16)
                cr.show_text(labels[i])

    def _bar(self, cr, w, h):
        d = self._data
        series_list = d.get("series", [])
        labels = d.get("labels", [])
        title = d.get("title", "")

        PL, PR, PT, PB = 44, 16, 26, 36
        pw, ph = w - PL - PR, h - PT - PB

        all_vals = [v for s in series_list for v in s.get("values", [])]
        if not all_vals:
            return
        vmax = max(all_vals) or 1

        n_groups = max(len(labels), max((len(s.get("values", [])) for s in series_list), default=1))
        n_ser = len(series_list)
        group_w = pw / max(n_groups, 1)
        bar_w = min(max(group_w * 0.7 / max(n_ser, 1), 4), 28)

        if title:
            cr.set_source_rgba(0.75, 0.88, 1.0, 0.85)
            self._font(cr, 11, bold=True)
            cr.move_to(PL, 18)
            cr.show_text(title)

        self._grid(cr, PL, PT, pw, ph, 0, vmax)
        self._axes(cr, PL, PT, pw, ph)

        for gi in range(n_groups):
            group_cx = PL + gi * group_w + group_w / 2
            total_bar_w = bar_w * n_ser + 2 * max(n_ser - 1, 0)
            bx0 = group_cx - total_bar_w / 2

            for si, s in enumerate(series_list):
                vals = s.get("values", [])
                if gi >= len(vals):
                    continue
                v = vals[gi]
                r, g, b = _CHART_COLORS[si % len(_CHART_COLORS)]
                bh = (v / vmax) * ph
                bx = bx0 + si * (bar_w + 2)
                by = PT + ph - bh

                cr.set_source_rgba(r, g, b, 0.75)
                if bh > 4:
                    cr.rectangle(bx, by + 4, bar_w, bh - 4)
                    cr.fill()
                    cr.arc(bx + bar_w / 2, by + 4, bar_w / 2, math.pi, 0)
                    cr.fill()
                else:
                    cr.rectangle(bx, by, bar_w, max(bh, 1))
                    cr.fill()

            if gi < len(labels):
                cr.set_source_rgba(0.55, 0.75, 1.0, 0.55)
                self._font(cr, 8)
                cr.move_to(group_cx - min(len(labels[gi]) * 3.5, group_w / 2), PT + ph + 18)
                cr.show_text(labels[gi])

        for si, s in enumerate(series_list):
            r, g, b = _CHART_COLORS[si % len(_CHART_COLORS)]
            lx = PL + pw - 90
            ly = 8 + si * 14
            cr.set_source_rgba(r, g, b, 0.9)
            cr.rectangle(lx, ly - 5, 10, 7)
            cr.fill()
            cr.set_source_rgba(0.72, 0.86, 1.0, 0.75)
            self._font(cr, 9)
            cr.move_to(lx + 13, ly + 1)
            cr.show_text(s.get("name", f"S{si + 1}"))

    def _donut(self, cr, w, h):
        d = self._data
        labels = d.get("labels", [])
        values = d.get("values", [])
        title = d.get("title", "")

        if not values:
            return
        total = sum(values) or 1

        if title:
            cr.set_source_rgba(0.75, 0.88, 1.0, 0.85)
            self._font(cr, 11, bold=True)
            cr.move_to(12, 18)
            cr.show_text(title)

        PT = 26 if title else 8
        avail_h = h - PT
        cx = w * 0.35
        cy = PT + avail_h / 2
        outer_r = min(cx - 12, avail_h / 2 - 8)
        inner_r = outer_r * 0.52

        if outer_r <= 0:
            return

        angle = -math.pi / 2
        for i, v in enumerate(values):
            if v <= 0:
                continue
            sweep = (v / total) * 2 * math.pi
            r, g, b = _CHART_COLORS[i % len(_CHART_COLORS)]
            cr.set_source_rgba(r, g, b, 0.85)
            cr.move_to(cx, cy)
            cr.arc(cx, cy, outer_r, angle, angle + sweep)
            cr.arc_negative(cx, cy, inner_r, angle + sweep, angle)
            cr.close_path()
            cr.fill()
            angle += sweep

        angle = -math.pi / 2
        for v in values:
            sweep = (v / total) * 2 * math.pi
            cr.set_source_rgba(0.03, 0.05, 0.14, 1.0)
            cr.set_line_width(1.5)
            cr.move_to(cx + math.cos(angle) * inner_r, cy + math.sin(angle) * inner_r)
            cr.line_to(cx + math.cos(angle) * outer_r, cy + math.sin(angle) * outer_r)
            cr.stroke()
            angle += sweep

        cr.set_source_rgba(0.03, 0.05, 0.14, 1.0)
        cr.arc(cx, cy, inner_r - 0.5, 0, 2 * math.pi)
        cr.fill()

        cr.set_source_rgba(0.82, 0.92, 1.0, 0.85)
        self._font(cr, 15, bold=True)
        total_s = f"{total:.0f}"
        cr.move_to(cx - len(total_s) * 4.5, cy + 6)
        cr.show_text(total_s)

        lx = cx + outer_r + 18
        n = len(values)
        ly0 = cy - n * 10
        for i, (lbl, v) in enumerate(zip(labels, values)):
            r, g, b = _CHART_COLORS[i % len(_CHART_COLORS)]
            ly = ly0 + i * 22
            cr.set_source_rgba(r, g, b, 0.85)
            cr.arc(lx + 5, ly, 5, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgba(0.72, 0.86, 1.0, 0.80)
            self._font(cr, 10)
            cr.move_to(lx + 14, ly + 4)
            cr.show_text(f"{lbl}  {v / total * 100:.1f}%")


class _WaveformWidget(Gtk.DrawingArea):
    """Equalizer bars: real audio levels when listening, synthetic animation otherwise."""

    _N = 26
    _W = 150
    _H = 48
    _BAR_W = 4
    _GAP = 2
    _LEVEL_SCALE = 0.04

    def __init__(self):
        super().__init__()
        self.set_content_width(self._W)
        self.set_content_height(self._H)
        self.set_draw_func(self._draw)
        self._phase = 0.0
        self._amplitude = 0.0
        self._target_amp = 0.0
        self._speed = 0.10
        self._r, self._g, self._b = _STATE_COLORS["idle"]
        self._timer_id = None
        self._live = False
        self._levels: deque = deque([0.0] * self._N, maxlen=self._N)

    def push_level(self, rms: float):
        self._levels.append(min(1.0, rms / self._LEVEL_SCALE))
        self.queue_draw()

    def set_state(self, state: str):
        self._r, self._g, self._b = _STATE_COLORS.get(state, _STATE_COLORS["idle"])
        entering_live = state == "listening" and not self._live
        self._live = (state == "listening")

        if entering_live:
            self._levels = deque([0.0] * self._N, maxlen=self._N)

        if state == "idle":
            self._target_amp = 0.0
            self._speed = 0.06
        elif state == "listening":
            self._target_amp = 1.0
            self._speed = 0.16
        elif state == "processing":
            self._target_amp = 0.42
            self._speed = 0.07
        elif state == "responding":
            self._target_amp = 0.70
            self._speed = 0.12
        elif state == "speaking":
            self._target_amp = 0.90
            self._speed = 0.15
        self._ensure_timer()

    def _ensure_timer(self):
        if not self._timer_id:
            self._timer_id = GLib.timeout_add(28, self._tick)

    def _tick(self):
        self._amplitude += (self._target_amp - self._amplitude) * 0.10
        if not self._live:
            self._phase += self._speed
            self.queue_draw()
        if self._target_amp < 0.01 and self._amplitude < 0.01 and not self._live:
            self._timer_id = None
            return False
        return True

    def _draw(self, _widget, cr, w, h):
        r, g, b = self._r, self._g, self._b
        total_w = self._N * (self._BAR_W + self._GAP) - self._GAP
        x0 = (w - total_w) / 2

        levels = list(self._levels) if self._live else None

        for i in range(self._N):
            if self._live:
                height_ratio = levels[i]
                bar_h = max(3.0, height_ratio * (h - 8) + 3)
                alpha = 0.25 + 0.75 * height_ratio
            else:
                fi = i / (self._N - 1)
                wave = (math.sin(self._phase + fi * 2 * math.pi) * 0.55 +
                        math.sin(self._phase * 1.6 + fi * 4 * math.pi + 1.2) * 0.45)
                height_ratio = (wave + 1) / 2
                envelope = math.sin(fi * math.pi) ** 0.5
                bar_h = max(3.0, self._amplitude * height_ratio * envelope * (h - 6) + 4)
                alpha = 0.30 + 0.70 * height_ratio * self._amplitude

            x = x0 + i * (self._BAR_W + self._GAP)
            y = (h - bar_h) / 2

            cr.set_source_rgba(r, g, b, alpha)
            bw = self._BAR_W
            rad = bw / 2
            cr.move_to(x + rad, y)
            cr.line_to(x + bw - rad, y)
            cr.arc(x + bw - rad, y + rad, rad, -math.pi / 2, 0)
            cr.line_to(x + bw, y + bar_h - rad)
            cr.arc(x + bw - rad, y + bar_h - rad, rad, 0, math.pi / 2)
            cr.line_to(x + rad, y + bar_h)
            cr.arc(x + rad, y + bar_h - rad, rad, math.pi / 2, math.pi)
            cr.line_to(x, y + rad)
            cr.arc(x + rad, y + rad, rad, math.pi, 3 * math.pi / 2)
            cr.close_path()
            cr.fill()


class _ResizeGrip(Gtk.DrawingArea):
    """Bottom-right corner drag handle for resizing the undecorated window."""

    _SIZE = 20

    def __init__(self, window: Gtk.Window):
        super().__init__()
        self._win = window
        self.set_content_width(self._SIZE)
        self.set_content_height(self._SIZE)
        self.set_halign(Gtk.Align.END)
        self.set_cursor(Gdk.Cursor.new_from_name("se-resize"))
        self.set_draw_func(self._draw)

        g = Gtk.GestureClick()
        g.set_button(1)
        g.connect("pressed", self._start_resize)
        self.add_controller(g)

    def _draw(self, _widget, cr, w, h):
        cr.set_source_rgba(0.35, 0.55, 1.0, 0.45)
        cr.set_line_width(1.5)
        for i in range(3):
            o = 4 + i * 5
            cr.move_to(w, h - o)
            cr.line_to(w - o, h)
            cr.stroke()

    def _start_resize(self, gesture, _n_press, x, y):
        surface = self._win.get_surface()
        if not surface:
            return
        ev = gesture.get_last_event(gesture.get_current_sequence())
        ts = ev.get_time() if ev else 0
        try:
            surface.begin_resize(
                Gdk.SurfaceEdge.SOUTH_EAST,
                gesture.get_device(),
                gesture.get_button(),
                x, y, ts,
            )
        except Exception:
            pass


class _MessageBlock(Gtk.Box):
    """One conversation turn: optional user prompt + JARVIS response + optional inline chart."""

    def __init__(self, user_text: "str | None" = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_opacity(0.0)

        if user_text:
            you = Gtk.Label(label=f"you  ·  {user_text}")
            you.add_css_class("user-label")
            you.set_halign(Gtk.Align.START)
            you.set_wrap(True)
            you.set_hexpand(True)
            self.append(you)

        self._resp = Gtk.Label(label="")
        self._resp.add_css_class("response-label")
        self._resp.set_halign(Gtk.Align.START)
        self._resp.set_valign(Gtk.Align.START)
        self._resp.set_wrap(True)
        self._resp.set_hexpand(True)
        self._resp.set_selectable(True)
        self.append(self._resp)

        self._chart: "_ChartWidget | None" = None

    def set_response(self, text: str) -> None:
        self._resp.set_text(text)

    def append_response(self, chunk: str) -> None:
        self._resp.set_text(self._resp.get_text() + chunk)

    def set_chart(self, data: dict) -> None:
        if self._chart is None:
            sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            sep.add_css_class("divider")
            self.append(sep)
            self._chart = _ChartWidget()
            self.append(self._chart)
        self._chart.load(data)


class JarvisOverlay(Gtk.Window):

    def __init__(self, app: Gtk.Application):
        super().__init__(application=app)
        self.set_decorated(False)
        self.set_resizable(True)
        self.add_css_class("jarvis-root")

        self._load_css()
        self._build_ui()
        self._setup_positioning()

        self._fade_opacity = 1.0
        self._fade_timer = None
        self._dot_timer = None
        self._dot_on = True
        self._current_block: "_MessageBlock | None" = None
        self._blocks: "list[_MessageBlock]" = []

    def _load_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _setup_positioning(self):
        # Always use regular window (layer shell anchors prevent free dragging)
        self.connect("map", self._reposition_x11)

    def _reposition_x11(self, _widget):
        try:
            display = Gdk.Display.get_default()
            monitor = display.get_monitors()[0]
            geom = monitor.get_geometry()
            win_w = self.get_width() or 920
            win_h = self.get_height() or 160
            x = geom.x + (geom.width - win_w) // 2
            y = geom.y + geom.height - win_h - 70
            import subprocess
            subprocess.run(
                ["xdotool", "search", "--name", "JARVIS", "windowmove", str(x), str(y)],
                capture_output=True,
            )
        except Exception:
            pass

    def _begin_drag(self, gesture, _n_press, _x, _y):
        """Start interactive window move on header click-drag."""
        surface = self.get_surface()
        if not surface:
            return
        event = gesture.get_last_event(gesture.get_current_sequence())
        ts = event.get_time() if event else 0
        device = gesture.get_device()
        # GTK4 ≥4.12 exposes begin_move; older versions use begin_interactive_move
        for method in ("begin_move", "begin_interactive_move"):
            fn = getattr(surface, method, None)
            if fn:
                try:
                    if method == "begin_move":
                        fn(device, gesture.get_button(), _x, _y, ts)
                    else:
                        fn(device, ts)
                    return
                except Exception:
                    continue

    def _build_ui(self):
        self.set_default_size(920, -1)

        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        outer.set_halign(Gtk.Align.CENTER)

        self._panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._panel.add_css_class("jarvis-panel")
        self._panel.set_size_request(900, -1)

        # Header row
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        header.set_margin_bottom(10)

        self._waveform = _WaveformWidget()
        header.append(self._waveform)

        title = Gtk.Label(label="J A R V I S")
        title.add_css_class("title-label")
        title.set_halign(Gtk.Align.START)
        title.set_valign(Gtk.Align.CENTER)
        header.append(title)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)

        self._status = Gtk.Label(label="STANDBY")
        self._status.add_css_class("status-label")
        self._status.set_valign(Gtk.Align.CENTER)
        header.append(self._status)

        # Drag header to move window
        drag = Gtk.GestureClick()
        drag.set_button(1)
        drag.connect("pressed", self._begin_drag)
        header.add_controller(drag)

        self._panel.append(header)

        hdr_sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        hdr_sep.add_css_class("header-sep")
        self._panel.append(hdr_sep)

        # Scrollable conversation log
        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.ALWAYS)
        self._scroll.set_min_content_height(60)
        self._scroll.set_max_content_height(460)
        self._scroll.set_propagate_natural_height(True)
        self._scroll.set_kinetic_scrolling(True)
        self._scroll.set_margin_top(14)
        self._scroll.set_visible(False)

        self._convo_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._convo_box.set_margin_bottom(4)
        self._scroll.set_child(self._convo_box)
        self._panel.append(self._scroll)

        self._panel.append(_ResizeGrip(self))

        outer.append(self._panel)
        self.set_child(outer)

    def _set_state(self, state: str):
        for s in _ALL_STATES:
            self._panel.remove_css_class(f"state-{s}")
        self._panel.add_css_class(f"state-{state}")
        self._waveform.set_state(state)

    # ── session management ────────────────────────────────────────────────────

    _MAX_VISUAL_BLOCKS = 15

    def new_session(self):
        """Clear the conversation log."""
        child = self._convo_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._convo_box.remove(child)
            child = nxt
        self._current_block = None
        self._blocks = []
        self._scroll.set_visible(False)

    def _prune_visual(self):
        """Drop the oldest turn block (+ its separator) when over the limit."""
        while len(self._blocks) > self._MAX_VISUAL_BLOCKS:
            old = self._blocks.pop(0)
            self._convo_box.remove(old)
            # The separator that now leads the list is stale — remove it
            first = self._convo_box.get_first_child()
            if first and not isinstance(first, _MessageBlock):
                self._convo_box.remove(first)

    def _new_block(self, user_text: "str | None") -> _MessageBlock:
        if self._convo_box.get_first_child() is not None:
            sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            sep.add_css_class("turn-sep")
            self._convo_box.append(sep)
        block = _MessageBlock(user_text=user_text)
        self._convo_box.append(block)
        self._blocks.append(block)
        self._prune_visual()
        self._scroll.set_visible(True)
        self._current_block = block
        self._fade_in(block)
        self._scroll_bottom()
        return block

    def _fade_in(self, widget: Gtk.Widget):
        def _step(op):
            op = min(1.0, op + 0.08)
            widget.set_opacity(op)
            if op < 1.0:
                GLib.timeout_add(16, _step, op)
            return False
        GLib.timeout_add(30, _step, 0.0)

    def _scroll_bottom(self):
        def _do():
            adj = self._scroll.get_vadjustment()
            adj.set_value(adj.get_upper() - adj.get_page_size())
            return False
        GLib.idle_add(_do)

    # ── public API (must be called on GTK main thread) ────────────────────────

    def push_audio_level(self, rms: float):
        self._waveform.push_level(rms)

    def show_chart(self, data: dict) -> None:
        if self._current_block:
            self._current_block.set_chart(data)
            self._scroll_bottom()

    def clear_chart(self) -> None:
        pass  # charts live inside their turn block and persist

    def show_listening(self):
        self._cancel_fade()
        self.set_opacity(1.0)
        self.set_visible(True)
        self._set_state("listening")
        self._start_dot_blink()

    def add_greeting(self, text: str):
        block = self._new_block(user_text=None)
        block.set_response(text)

    def show_processing(self):
        self._cancel_dot_blink()
        self._status.set_text("PROCESSING")
        self._set_state("processing")

    def show_user_text(self, text: str):
        self._new_block(user_text=text)
        self._status.set_text("RESPONDING")
        self._set_state("responding")

    def show_tool(self, tool_name: str):
        readable = tool_name.replace("_", " ").title()
        self._status.set_text(f"⚙  {readable}")

    def append_response(self, chunk: str):
        if self._current_block:
            self._current_block.append_response(chunk)
            self._scroll_bottom()

    def show_speaking(self):
        self._status.set_text("SPEAKING")
        self._set_state("speaking")

    def schedule_hide(self, delay_ms: int = 5000):
        GLib.timeout_add(delay_ms, self._begin_fade)

    # ── blinking dot ──────────────────────────────────────────────────────────

    def _start_dot_blink(self):
        self._dot_on = True
        self._update_dot()
        if not self._dot_timer:
            self._dot_timer = GLib.timeout_add(700, self._dot_tick)

    def _dot_tick(self):
        if self._waveform._live:
            self._dot_on = not self._dot_on
            self._update_dot()
            return True
        self._dot_timer = None
        return False

    def _update_dot(self):
        dot = "⬤ " if self._dot_on else "  "
        self._status.set_markup(f'<span foreground="#5599FF">{dot}</span>LISTENING')

    # ── fade out ──────────────────────────────────────────────────────────────

    def _cancel_dot_blink(self):
        if self._dot_timer:
            GLib.source_remove(self._dot_timer)
            self._dot_timer = None

    def _begin_fade(self) -> bool:
        self._cancel_dot_blink()
        self._fade_opacity = 1.0
        self._set_state("idle")
        self._fade_timer = GLib.timeout_add(35, self._fade_step)
        return False

    def _fade_step(self) -> bool:
        self._fade_opacity -= 0.04
        if self._fade_opacity <= 0:
            self.set_visible(False)
            self.set_opacity(1.0)
            self._fade_timer = None
            return False
        self.set_opacity(self._fade_opacity)
        return True

    def _cancel_fade(self):
        if self._fade_timer:
            GLib.source_remove(self._fade_timer)
            self._fade_timer = None
        self.set_opacity(1.0)
