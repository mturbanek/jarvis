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

# (r, g, b) accent per state
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
    background: linear-gradient(150deg, rgba(5,12,32,0.97) 0%, rgba(3,7,18,0.98) 100%);
    border: 1px solid rgba(52, 140, 255, 0.40);
    border-top: 2px solid rgba(52, 140, 255, 0.55);
    border-radius: 20px;
    padding: 20px 28px 22px 28px;
    box-shadow:
        0 16px 48px rgba(0,0,0,0.75),
        inset 0 1px 0 rgba(255,255,255,0.05);
}

.state-listening {
    border-color: rgba(52, 140, 255, 0.85);
    border-top-color: rgba(80, 170, 255, 0.90);
    box-shadow:
        0 16px 48px rgba(0,0,0,0.75),
        0 0 40px rgba(52, 140, 255, 0.30),
        0 0 80px rgba(52, 140, 255, 0.12),
        inset 0 1px 0 rgba(255,255,255,0.07);
}

.state-processing {
    border-color: rgba(255, 178, 30, 0.85);
    border-top-color: rgba(255, 205, 80, 0.90);
    box-shadow:
        0 16px 48px rgba(0,0,0,0.75),
        0 0 40px rgba(255, 178, 30, 0.28),
        0 0 80px rgba(255, 178, 30, 0.10),
        inset 0 1px 0 rgba(255,255,255,0.07);
}

.state-responding {
    border-color: rgba(20, 215, 245, 0.85);
    border-top-color: rgba(60, 235, 255, 0.90);
    box-shadow:
        0 16px 48px rgba(0,0,0,0.75),
        0 0 40px rgba(20, 215, 245, 0.28),
        0 0 80px rgba(20, 215, 245, 0.10),
        inset 0 1px 0 rgba(255,255,255,0.07);
}

.state-speaking {
    border-color: rgba(165, 82, 255, 0.85);
    border-top-color: rgba(195, 120, 255, 0.90);
    box-shadow:
        0 16px 48px rgba(0,0,0,0.75),
        0 0 40px rgba(165, 82, 255, 0.28),
        0 0 80px rgba(165, 82, 255, 0.10),
        inset 0 1px 0 rgba(255,255,255,0.07);
}

.title-label {
    color: #5599FF;
    font-family: monospace;
    font-size: 14px;
    font-weight: bold;
    letter-spacing: 6px;
}

.status-label {
    color: rgba(100, 160, 255, 0.80);
    font-family: monospace;
    font-size: 10px;
    font-weight: bold;
    letter-spacing: 3px;
}

.user-label {
    color: rgba(150, 185, 245, 0.75);
    font-family: sans-serif;
    font-size: 13px;
    font-style: italic;
    margin-top: 6px;
}

.response-label {
    color: rgba(225, 238, 255, 0.96);
    font-family: sans-serif;
    font-size: 16px;
}

.divider {
    background-color: rgba(52, 120, 255, 0.20);
    min-height: 1px;
    margin-top: 12px;
    margin-bottom: 12px;
}
"""

_ALL_STATES = ("idle", "listening", "processing", "responding", "speaking")

_CHART_COLORS = [
    (0.20, 0.52, 1.00),  # blue
    (0.08, 0.82, 0.92),  # cyan
    (0.65, 0.35, 1.00),  # purple
    (1.00, 0.70, 0.12),  # amber
    (0.20, 0.85, 0.55),  # green
    (1.00, 0.35, 0.40),  # coral
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

    # ── dispatch ─────────────────────────────────────────────────────────────

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

    # ── shared helpers ────────────────────────────────────────────────────────

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

    # ── line ─────────────────────────────────────────────────────────────────

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

            # Area fill
            cr.set_source_rgba(r, g, b, 0.09)
            cr.move_to(gx(0), PT + ph)
            cr.line_to(gx(0), gy(vals[0]))
            for i, v in enumerate(vals[1:], 1):
                cr.line_to(gx(i), gy(v))
            cr.line_to(gx(len(vals) - 1), PT + ph)
            cr.close_path()
            cr.fill()

            # Line
            cr.set_source_rgba(r, g, b, 0.90)
            cr.set_line_width(1.5)
            cr.move_to(gx(0), gy(vals[0]))
            for i, v in enumerate(vals[1:], 1):
                cr.line_to(gx(i), gy(v))
            cr.stroke()

            # Legend chip
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

    # ── bar ──────────────────────────────────────────────────────────────────

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

    # ── donut ─────────────────────────────────────────────────────────────────

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

        # Draw segments
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

        # Gap lines between segments
        angle = -math.pi / 2
        for v in values:
            sweep = (v / total) * 2 * math.pi
            cr.set_source_rgba(0.03, 0.05, 0.14, 1.0)
            cr.set_line_width(1.5)
            cr.move_to(cx + math.cos(angle) * inner_r, cy + math.sin(angle) * inner_r)
            cr.line_to(cx + math.cos(angle) * outer_r, cy + math.sin(angle) * outer_r)
            cr.stroke()
            angle += sweep

        # Inner hole
        cr.set_source_rgba(0.03, 0.05, 0.14, 1.0)
        cr.arc(cx, cy, inner_r - 0.5, 0, 2 * math.pi)
        cr.fill()

        # Centre label
        cr.set_source_rgba(0.82, 0.92, 1.0, 0.85)
        self._font(cr, 15, bold=True)
        total_s = f"{total:.0f}"
        cr.move_to(cx - len(total_s) * 4.5, cy + 6)
        cr.show_text(total_s)

        # Legend
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

    _N = 22
    _W = 130
    _H = 44
    _BAR_W = 4
    _GAP = 2
    _LEVEL_SCALE = 0.04  # RMS value that maps to a full-height bar

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
        """Feed one real audio RMS sample (called from the GTK main thread)."""
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


class JarvisOverlay(Gtk.Window):

    def __init__(self, app: Gtk.Application):
        super().__init__(application=app)
        self.set_decorated(False)
        self.set_resizable(False)
        self.add_css_class("jarvis-root")

        self._load_css()
        self._build_ui()
        self._setup_positioning()

        self._fade_opacity = 1.0
        self._fade_timer = None
        self._dot_timer = None
        self._dot_on = True

    def _load_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _setup_positioning(self):
        if _LAYER_SHELL:
            _ls.init_for_window(self)
            _ls.set_layer(self, _ls.Layer.OVERLAY)
            _ls.set_anchor(self, _ls.Edge.BOTTOM, True)
            _ls.set_margin(self, _ls.Edge.BOTTOM, 60)
            _ls.set_keyboard_mode(self, _ls.KeyboardMode.NONE)
        else:
            self.connect("map", self._reposition_x11)

    def _reposition_x11(self, _widget):
        try:
            display = Gdk.Display.get_default()
            monitor = display.get_monitors()[0]
            geom = monitor.get_geometry()
            win_w = self.get_width() or 780
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

    def _build_ui(self):
        self.set_default_size(780, -1)

        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        outer.set_halign(Gtk.Align.CENTER)

        self._panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._panel.add_css_class("jarvis-panel")
        self._panel.set_size_request(760, -1)

        # Header row
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        header.set_margin_bottom(12)

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

        self._panel.append(header)

        self._user_lbl = Gtk.Label(label="")
        self._user_lbl.add_css_class("user-label")
        self._user_lbl.set_halign(Gtk.Align.START)
        self._user_lbl.set_wrap(True)
        self._user_lbl.set_max_width_chars(80)
        self._user_lbl.set_visible(False)
        self._panel.append(self._user_lbl)

        self._divider = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self._divider.add_css_class("divider")
        self._divider.set_visible(False)
        self._panel.append(self._divider)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_max_content_height(240)
        scroll.set_propagate_natural_height(True)
        scroll.set_visible(False)
        self._scroll = scroll

        self._resp_lbl = Gtk.Label(label="")
        self._resp_lbl.add_css_class("response-label")
        self._resp_lbl.set_halign(Gtk.Align.START)
        self._resp_lbl.set_valign(Gtk.Align.START)
        self._resp_lbl.set_wrap(True)
        self._resp_lbl.set_max_width_chars(76)
        self._resp_lbl.set_selectable(True)
        scroll.set_child(self._resp_lbl)
        self._panel.append(scroll)

        # Chart area — hidden until show_chart() is called
        self._chart_sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self._chart_sep.add_css_class("divider")
        self._chart_sep.set_visible(False)
        self._panel.append(self._chart_sep)

        self._chart = _ChartWidget()
        self._chart.set_visible(False)
        self._panel.append(self._chart)

        outer.append(self._panel)
        self.set_child(outer)

    def _set_state(self, state: str):
        for s in _ALL_STATES:
            self._panel.remove_css_class(f"state-{s}")
        self._panel.add_css_class(f"state-{state}")
        self._waveform.set_state(state)

    # ── public state transitions (must be called on the main thread) ──

    def push_audio_level(self, rms: float):
        self._waveform.push_level(rms)

    def show_chart(self, data: dict) -> None:
        self._chart.load(data)
        self._chart.set_visible(True)
        self._chart_sep.set_visible(True)

    def clear_chart(self) -> None:
        self._chart.clear()
        self._chart.set_visible(False)
        self._chart_sep.set_visible(False)

    def show_listening(self):
        self._cancel_fade()
        self.set_opacity(1.0)
        self.set_visible(True)
        self._user_lbl.set_visible(False)
        self._divider.set_visible(False)
        self._scroll.set_visible(False)
        self._resp_lbl.set_text("")
        self.clear_chart()
        self._set_state("listening")
        self._start_dot_blink()

    def _start_dot_blink(self):
        self._dot_on = True
        self._update_dot()
        if not self._dot_timer:
            self._dot_timer = GLib.timeout_add(700, self._dot_tick)

    def _dot_tick(self):
        if self._waveform._live:  # still listening
            self._dot_on = not self._dot_on
            self._update_dot()
            return True
        self._dot_timer = None
        return False

    def _update_dot(self):
        dot = "⬤ " if self._dot_on else "  "
        self._status.set_markup(f'<span foreground="#5599FF">{dot}</span>LISTENING')

    def show_processing(self):
        self._cancel_dot_blink()
        self._status.set_text("PROCESSING")
        self._set_state("processing")

    def show_user_text(self, text: str):
        self._user_lbl.set_text(f"You  →  {text}")
        self._user_lbl.set_visible(True)
        self._divider.set_visible(True)
        self._scroll.set_visible(True)
        self._status.set_text("RESPONDING")
        self._set_state("responding")

    def show_tool(self, tool_name: str):
        readable = tool_name.replace("_", " ").title()
        self._status.set_text(f"⚙  {readable}")

    def append_response(self, chunk: str):
        self._resp_lbl.set_text(self._resp_lbl.get_text() + chunk)
        adj = self._scroll.get_vadjustment()
        adj.set_value(adj.get_upper())

    def show_speaking(self):
        self._status.set_text("SPEAKING")
        self._set_state("speaking")

    def schedule_hide(self, delay_ms: int = 5000):
        GLib.timeout_add(delay_ms, self._begin_fade)

    # ── fade out ──

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
