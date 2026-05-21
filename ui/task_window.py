"""
NovaMind Task UI — Animated dark cyberpunk theme.
Fully self-contained PyQt6 — no Ursina dependency.

Features
────────
• Frameless floating window with drag-to-move title bar
• Embedded 2D animated task visualiser (QPainter 30 fps) — always works
• Pulsing animated status dots and glowing progress bars
• Task cards with live status, step progress, error display
• Animated background grid + particle field
• Colour-coded console with timestamp colouring
• System tray + floating orb minimised state
"""
import math
import random
import sys
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QScrollArea, QFrame,
    QSizePolicy, QSystemTrayIcon, QMenu, QSplitter,
    QProgressBar,
)
from PyQt6.QtCore import (
    Qt, QTimer, QObject, pyqtSignal, QPoint, QPointF, QRectF, QSize,
    QPropertyAnimation, QEasingCurve,
)
from PyQt6.QtGui import (
    QColor, QFont, QIcon, QAction, QPainter, QBrush, QPen,
    QRadialGradient, QLinearGradient, QConicalGradient,
    QFontDatabase, QKeySequence, QShortcut, QPalette, QTextCursor,
    QPolygonF,
)

logger = logging.getLogger("TaskUI")

# ─────────────────────────────────────────────────────────────────────────────
#  Theme
# ─────────────────────────────────────────────────────────────────────────────

C: Dict[str, str] = {
    "bg_primary":    "#070b14",
    "bg_secondary":  "#0d1422",
    "bg_card":       "#131d30",
    "bg_input":      "#0a1020",
    "accent_cyan":   "#00d4ff",
    "accent_blue":   "#3b82f6",
    "accent_purple": "#8b5cf6",
    "accent_pink":   "#ec4899",
    "text_primary":  "#e2e8f0",
    "text_secondary":"#94a3b8",
    "text_muted":    "#4a5568",
    "success":       "#22c55e",
    "warning":       "#f59e0b",
    "error":         "#ef4444",
    "border":        "#1a2540",
}

STATUS_COLORS: Dict[str, str] = {
    "pending":           C["text_muted"],
    "running":           C["accent_cyan"],
    "retrying":          C["warning"],
    "verifying":         C["accent_blue"],
    "success":           C["success"],
    "done":              C["success"],
    "failed":            C["error"],
    "cancelled":         C["text_muted"],
    "needs_confirmation": C["warning"],
}

STATUS_QC: Dict[str, QColor] = {k: QColor(v) for k, v in STATUS_COLORS.items()}

APP_STYLE = f"""
QWidget {{
    background-color: {C['bg_primary']};
    color: {C['text_primary']};
    font-family: 'Segoe UI', 'Inter', 'Arial', sans-serif;
    font-size: 13px;
}}
QScrollBar:vertical {{
    background: {C['bg_secondary']};
    width: 5px;
    border-radius: 2px;
}}
QScrollBar::handle:vertical {{
    background: {C['border']};
    border-radius: 2px;
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: {C['bg_secondary']};
    height: 5px;
}}
QScrollBar::handle:horizontal {{
    background: {C['border']};
    border-radius: 2px;
}}
QTextEdit, QLineEdit {{
    background-color: {C['bg_input']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    padding: 6px 10px;
    color: {C['text_primary']};
    selection-background-color: {C['accent_blue']};
}}
QTextEdit:focus, QLineEdit:focus {{
    border-color: {C['accent_cyan']};
}}
QPushButton {{
    background-color: {C['bg_card']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    padding: 7px 16px;
    color: {C['text_primary']};
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {C['accent_blue']};
    border-color: {C['accent_blue']};
    color: white;
}}
QPushButton:pressed {{
    background-color: {C['accent_cyan']};
    color: {C['bg_primary']};
}}
QPushButton#primary {{
    background-color: {C['accent_cyan']};
    color: {C['bg_primary']};
    font-weight: 700;
    border: none;
}}
QPushButton#primary:hover {{ background-color: #00b8e0; }}
QPushButton#primary:pressed {{ background-color: #009bbf; }}
QFrame#card {{
    background-color: {C['bg_card']};
    border: 1px solid {C['border']};
    border-radius: 8px;
}}
QLabel#heading {{
    font-size: 15px; font-weight: 700;
    color: {C['text_primary']};
}}
QLabel#muted {{
    color: {C['text_muted']};
    font-size: 11px;
}}
QProgressBar {{
    background-color: {C['bg_secondary']};
    border: none; border-radius: 3px; height: 4px;
    text-align: center;
}}
QProgressBar::chunk {{
    background-color: {C['accent_cyan']};
    border-radius: 3px;
}}
QMenu {{
    background-color: {C['bg_card']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{ padding: 6px 20px; border-radius: 4px; }}
QMenu::item:selected {{ background-color: {C['accent_blue']}; color: white; }}
"""


# ─────────────────────────────────────────────────────────────────────────────
#  Animated background widget (particle field + grid)
# ─────────────────────────────────────────────────────────────────────────────

class _Particle:
    __slots__ = ("x", "y", "vx", "vy", "alpha", "size", "color_idx")

    def __init__(self, w: int, h: int):
        self.x = random.uniform(0, w)
        self.y = random.uniform(0, h)
        self.vx = random.uniform(-0.3, 0.3)
        self.vy = random.uniform(-0.5, -0.1)
        self.alpha = random.uniform(30, 120)
        self.size = random.uniform(1.0, 2.5)
        self.color_idx = random.randint(0, 3)

    def step(self, w: int, h: int):
        self.x += self.vx
        self.y += self.vy
        self.alpha -= 0.3
        if self.alpha <= 0 or self.y < 0:
            self.__init__(w, h)
            self.y = h


_PARTICLE_COLORS = [
    QColor(0, 212, 255),
    QColor(59, 130, 246),
    QColor(139, 92, 246),
    QColor(236, 72, 153),
]


class AnimatedBackground(QWidget):
    """Draws an animated grid + floating particle field."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._t = 0.0
        self._particles: List[_Particle] = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def _ensure_particles(self):
        w, h = max(self.width(), 1), max(self.height(), 1)
        while len(self._particles) < 35:
            p = _Particle(w, h)
            p.y = random.uniform(0, h)
            self._particles.append(p)

    def _tick(self):
        self._t += 0.016
        w, h = max(self.width(), 1), max(self.height(), 1)
        self._ensure_particles()
        for p in self._particles:
            p.step(w, h)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Background
        p.fillRect(self.rect(), QColor(C["bg_primary"]))

        # Animated grid
        grid_spacing = 40
        phase = (self._t * 8) % grid_spacing
        pen = QPen(QColor(0, 40, 80, 45))
        pen.setWidthF(0.5)
        p.setPen(pen)
        x = -phase
        while x < w:
            p.drawLine(int(x), 0, int(x), h)
            x += grid_spacing
        y = -phase
        while y < h:
            p.drawLine(0, int(y), w, int(y))
            y += grid_spacing

        # Horizon glow
        glow_y = h * 0.6
        grad = QLinearGradient(0, glow_y - 60, 0, glow_y + 60)
        grad.setColorAt(0.0, QColor(0, 0, 0, 0))
        grad.setColorAt(0.5, QColor(0, 212, 255, 8))
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(0, glow_y - 60, w, 120), QBrush(grad))

        # Particles
        p.setPen(Qt.PenStyle.NoPen)
        for pt in self._particles:
            c = _PARTICLE_COLORS[pt.color_idx]
            c.setAlpha(int(pt.alpha))
            p.setBrush(QBrush(c))
            p.drawEllipse(QPointF(pt.x, pt.y), pt.size, pt.size)

        p.end()


# ─────────────────────────────────────────────────────────────────────────────
#  2-D animated task visualiser (the embedded "game view")
# ─────────────────────────────────────────────────────────────────────────────

class TaskVisualizer(QWidget):
    """
    2-D cyberpunk task visualiser — always works inside the PyQt6 window.

    • Central AI Core pulses
    • Each task is an orbiting glowing orb (colour = status)
    • Running orbs spin a bright ring around them
    • Success orbs leave a fading sparkle trail
    • Background has a slow-rotating hex grid
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(200)
        self.setMaximumHeight(240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self._t = 0.0
        self._tasks: List[Dict] = []
        self._sparkles: List[Dict] = []   # {x, y, r, alpha, color}
        self._score = 0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)              # ~30 fps

    # ── public API ─────────────────────────────────────────────────────────

    def update_tasks(self, tasks: List[Dict]):
        self._tasks = [t for t in (tasks or []) if t]

    def add_sparkle(self, cx: float, cy: float, color: QColor):
        """Spawn a small burst of sparkle dots at (cx, cy)."""
        for _ in range(8):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(1.5, 4.0)
            self._sparkles.append({
                "x": cx, "y": cy,
                "vx": math.cos(angle) * speed,
                "vy": math.sin(angle) * speed,
                "alpha": 255,
                "size": random.uniform(2, 5),
                "color": QColor(color),
            })

    # ── animation tick ──────────────────────────────────────────────────────

    def _tick(self):
        self._t += 0.033
        # Age sparkles
        self._sparkles = [s for s in self._sparkles if s["alpha"] > 0]
        for s in self._sparkles:
            s["x"] += s["vx"]
            s["y"] += s["vy"]
            s["vy"] += 0.1          # gravity
            s["alpha"] = max(0, s["alpha"] - 8)
        self.update()

    # ── paint ───────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        t = self._t

        # Background
        painter.fillRect(self.rect(), QColor(C["bg_secondary"]))

        # Hex grid (rotates slowly)
        self._draw_hex_grid(painter, w, h, t)

        # Central AI Core
        cx, cy = w / 2, h / 2
        self._draw_core(painter, cx, cy, t)

        # Task orbs
        tasks = self._tasks
        n = len(tasks)
        for i, task in enumerate(tasks):
            self._draw_orb(painter, task, i, n, cx, cy, t)

        # Sparkles
        painter.setPen(Qt.PenStyle.NoPen)
        for s in self._sparkles:
            c = QColor(s["color"])
            c.setAlpha(s["alpha"])
            painter.setBrush(QBrush(c))
            painter.drawEllipse(
                QPointF(s["x"], s["y"]), s["size"], s["size"]
            )

        # HUD overlay
        self._draw_hud(painter, w, h, tasks)

        painter.end()

    def _draw_hex_grid(self, p: QPainter, w: int, h: int, t: float):
        hex_r = 22
        horiz = hex_r * math.sqrt(3)
        vert = hex_r * 1.5
        pen = QPen(QColor(0, 60, 100, 30))
        pen.setWidthF(0.6)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        off_x = (t * 4) % horiz
        off_y = (t * 2) % (vert * 2)

        col = -2
        while col * horiz < w + horiz * 2:
            row = -2
            while row * vert * 2 < h + vert * 4:
                hx = col * horiz + (hex_r * math.sqrt(3) / 2 if row % 2 else 0) + off_x
                hy = row * vert * 2 + off_y
                pts = []
                for a in range(6):
                    angle = math.radians(a * 60 - 30)
                    pts.append(QPointF(hx + hex_r * math.cos(angle),
                                       hy + hex_r * math.sin(angle)))
                poly = QPolygonF(pts)
                p.drawPolygon(poly)
                row += 1
            col += 1

    def _draw_core(self, p: QPainter, cx: float, cy: float, t: float):
        pulse = 0.18 * math.sin(t * 2.8)
        r_core = 18 + pulse * 18

        # Outer glow rings (3 rings, different phases)
        for i, (ring_r, alpha) in enumerate(
            [(r_core + 28, 18), (r_core + 18, 32), (r_core + 8, 55)]
        ):
            ring_pulse = math.sin(t * 2.8 + i * 0.9) * 6
            gr = QRadialGradient(cx, cy, ring_r + ring_pulse)
            gc = QColor(0, 212, 255, alpha)
            gc2 = QColor(0, 212, 255, 0)
            gr.setColorAt(0.6, gc)
            gr.setColorAt(1.0, gc2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(gr))
            p.drawEllipse(QPointF(cx, cy),
                          ring_r + ring_pulse, ring_r + ring_pulse)

        # Core body
        gr = QRadialGradient(cx - r_core * 0.3, cy - r_core * 0.3, r_core * 1.5)
        gr.setColorAt(0.0, QColor(180, 240, 255, 255))
        gr.setColorAt(0.4, QColor(0, 212, 255, 230))
        gr.setColorAt(1.0, QColor(0, 60, 120, 200))
        p.setBrush(QBrush(gr))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), r_core, r_core)

        # Spinning ring
        p.save()
        p.translate(cx, cy)
        p.rotate(t * 55)
        pen = QPen(QColor(0, 212, 255, 130))
        pen.setWidthF(1.5)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(0, 0), r_core + 6, r_core * 0.35)
        p.restore()

        # Counter-spin ring
        p.save()
        p.translate(cx, cy)
        p.rotate(-t * 38)
        pen2 = QPen(QColor(139, 92, 246, 90))
        pen2.setWidthF(1.0)
        p.setPen(pen2)
        p.drawEllipse(QPointF(0, 0), r_core + 3, r_core * 0.5)
        p.restore()

    def _draw_orb(self, p: QPainter, task: Dict, idx: int,
                  n: int, cx: float, cy: float, t: float):
        status = task.get("status", "pending")
        qc = STATUS_QC.get(status, QColor(C["text_muted"]))

        rings = max(1, (n + 2) // 3)
        ring_idx = idx % 3
        row_idx  = idx // 3
        base_r   = 48 + ring_idx * 28
        h_offset = row_idx * 14

        speed = 0.35 - idx * 0.015
        angle = (idx / max(n, 1)) * math.tau + t * speed
        ox = cx + math.cos(angle) * base_r
        oy = cy + math.sin(angle) * base_r * 0.42 + h_offset  # flatten vertically

        orb_r = 7.0
        if status in ("running", "retrying"):
            orb_r += 2.5 * math.sin(t * 6 + idx)

        # Orbit path (dim)
        pen = QPen(QColor(qc.red(), qc.green(), qc.blue(), 25))
        pen.setWidthF(0.8)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), base_r, base_r * 0.42)

        # Spinning ring for running tasks
        if status in ("running", "retrying"):
            p.save()
            p.translate(ox, oy)
            p.rotate(t * 180 + idx * 30)
            rpen = QPen(QColor(qc.red(), qc.green(), qc.blue(), 180))
            rpen.setWidthF(1.5)
            p.setPen(rpen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(0, 0), orb_r + 5, orb_r + 5)
            p.restore()

        # Glow halo
        gr = QRadialGradient(ox, oy, orb_r * 3)
        gr.setColorAt(0.0, QColor(qc.red(), qc.green(), qc.blue(), 60))
        gr.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(gr))
        p.drawEllipse(QPointF(ox, oy), orb_r * 3, orb_r * 3)

        # Orb body
        gr2 = QRadialGradient(ox - orb_r * 0.35, oy - orb_r * 0.35, orb_r * 1.5)
        gr2.setColorAt(0.0, QColor(
            min(255, qc.red() + 80),
            min(255, qc.green() + 80),
            min(255, qc.blue() + 80), 255
        ))
        gr2.setColorAt(0.5, QColor(qc.red(), qc.green(), qc.blue(), 230))
        gr2.setColorAt(1.0, QColor(
            max(0, qc.red() - 60),
            max(0, qc.green() - 60),
            max(0, qc.blue() - 60), 180
        ))
        p.setBrush(QBrush(gr2))
        p.drawEllipse(QPointF(ox, oy), orb_r, orb_r)

        # Label
        summary = (task.get("summary") or task.get("request") or "")[:18]
        if summary:
            lc = QColor(qc.red(), qc.green(), qc.blue(), 200)
            p.setPen(QPen(lc))
            p.setFont(QFont("Segoe UI", 7))
            p.drawText(
                QRectF(ox - 40, oy + orb_r + 2, 80, 14),
                Qt.AlignmentFlag.AlignCenter, summary
            )

    def _draw_hud(self, p: QPainter, w: int, h: int, tasks: List[Dict]):
        running = sum(1 for t in tasks if t.get("status") == "running")
        done    = sum(1 for t in tasks if t.get("status") in ("success", "done"))
        failed  = sum(1 for t in tasks if t.get("status") == "failed")

        p.setPen(QPen(QColor(C["text_muted"])))
        p.setFont(QFont("Segoe UI", 8))

        label = (
            f"▶ {running} running   ✓ {done} done   ✗ {failed} failed"
            f"   · {len(tasks)} total"
        )
        p.drawText(
            QRectF(0, h - 18, w, 16),
            Qt.AlignmentFlag.AlignCenter, label
        )

        # Scan-line overlay
        line_pen = QPen(QColor(0, 0, 0, 18))
        line_pen.setWidthF(1.0)
        p.setPen(line_pen)
        y = 0
        while y < h:
            p.drawLine(0, y, w, y)
            y += 3


# ─────────────────────────────────────────────────────────────────────────────
#  Pulsing status dot
# ─────────────────────────────────────────────────────────────────────────────

class PulsingDot(QWidget):
    """A small dot that pulses smoothly. Replaces the plain QLabel ●."""

    def __init__(self, size: int = 10, parent=None):
        super().__init__(parent)
        self._dot_size = size
        self.setFixedSize(size + 8, size + 8)
        self._t = 0.0
        self._color = QColor(C["text_muted"])
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def set_color(self, color_hex: str):
        self._color = QColor(color_hex)
        self.update()

    def _tick(self):
        self._t += 0.05
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() / 2
        cy = self.height() / 2
        r = self._dot_size / 2

        pulse = 0.35 * math.sin(self._t * 2.5)
        glow_r = r * (1.8 + pulse)

        gr = QRadialGradient(cx, cy, glow_r * 1.8)
        gc = QColor(self._color)
        gc.setAlpha(int(50 * (1 + pulse)))
        gr.setColorAt(0.0, gc)
        gr.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(gr))
        p.drawEllipse(QPointF(cx, cy), glow_r * 1.8, glow_r * 1.8)

        body = QColor(self._color)
        p.setBrush(QBrush(body))
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
#  Floating orb (minimised state)
# ─────────────────────────────────────────────────────────────────────────────

class FloatingOrb(QWidget):
    """Pulsing cyan orb that floats above the taskbar when window is hidden."""

    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(68, 68)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - 90, screen.height() - 140)

        self._t = 0.0
        self._task_count = 0
        self._glow = QColor(C["accent_cyan"])
        self._drag_pos: Optional[QPoint] = None

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)
        self.hide()

    def _tick(self):
        self._t += 0.04
        self.update()

    def set_task_count(self, n: int):
        self._task_count = n
        self.update()

    def set_color(self, color_hex: str):
        self._glow = QColor(color_hex)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self.rect().center()
        cx, cy = c.x(), c.y()
        r = 22

        pulse = 0.25 * math.sin(self._t * 2.5)
        glow_r = r * (2.0 + pulse)

        # Outer glow
        gr = QRadialGradient(cx, cy, glow_r)
        gc = QColor(self._glow)
        gc.setAlpha(int(70 * (1 + pulse * 0.6)))
        gr.setColorAt(0.0, gc)
        gr.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(gr))
        p.drawEllipse(QPointF(cx, cy), glow_r, glow_r)

        # Spinning ring
        p.save()
        p.translate(cx, cy)
        p.rotate(self._t * 50)
        ring_pen = QPen(QColor(self._glow))
        ring_pen.setWidthF(1.5)
        _rc = ring_pen.color()
        _rc.setAlpha(120)
        ring_pen.setColor(_rc)
        p.setPen(ring_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(0, 0), r + 7, r + 7)
        p.restore()

        # Core
        body_gr = QRadialGradient(cx - r * 0.3, cy - r * 0.3, r * 1.6)
        body_gr.setColorAt(0.0, QColor(200, 240, 255, 255))
        body_gr.setColorAt(0.5, self._glow)
        body_gr.setColorAt(1.0, QColor(
            max(0, self._glow.red() - 60),
            max(0, self._glow.green() - 60),
            max(0, self._glow.blue() - 60), 200
        ))
        p.setBrush(QBrush(body_gr))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), r, r)

        # Highlight
        p.setBrush(QBrush(QColor(255, 255, 255, 130)))
        p.drawEllipse(QPointF(cx - r * 0.3, cy - r * 0.3),
                      r * 0.45, r * 0.45)

        # Badge
        if self._task_count > 0:
            bx, by = cx + 16, cy - 16
            p.setBrush(QBrush(QColor(C["warning"])))
            p.drawEllipse(QPointF(bx, by), 9, 9)
            p.setPen(QPen(QColor("white")))
            p.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
            p.drawText(
                QRectF(bx - 9, by - 9, 18, 18),
                Qt.AlignmentFlag.AlignCenter, str(self._task_count)
            )

        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (
                e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            self.clicked.emit()

    def mouseMoveEvent(self, e):
        if self._drag_pos:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, _e):
        self._drag_pos = None


# ─────────────────────────────────────────────────────────────────────────────
#  Glowing progress bar
# ─────────────────────────────────────────────────────────────────────────────

class GlowProgressBar(QWidget):
    """Animated progress bar with trailing glow."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(6)
        self._value = 0
        self._maximum = 100
        self._t = 0.0
        self._color = QColor(C["accent_cyan"])

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def _tick(self):
        self._t += 0.05
        self.update()

    def set_value(self, v: int):
        self._value = v
        self.update()

    def set_maximum(self, m: int):
        self._maximum = max(1, m)
        self.update()

    def set_color(self, color: QColor):
        self._color = color

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        ratio = self._value / self._maximum
        fill_w = max(0.0, ratio * w)

        # Track
        p.setBrush(QBrush(QColor(20, 30, 50)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)

        if fill_w < 1:
            p.end()
            return

        # Fill gradient
        grad = QLinearGradient(0, 0, fill_w, 0)
        base = self._color
        grad.setColorAt(0.0, QColor(base.red() // 3, base.green() // 3, base.blue() // 3, 180))
        grad.setColorAt(1.0, base)
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(QRectF(0, 0, fill_w, h), h / 2, h / 2)

        # Animated glow tip
        pulse = 0.5 + 0.5 * math.sin(self._t * 4)
        tip_x = fill_w
        gr = QRadialGradient(tip_x, h / 2, 12)
        gc = QColor(base.red(), base.green(), base.blue(),
                    int(180 * pulse))
        gr.setColorAt(0.0, gc)
        gr.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(gr))
        p.drawEllipse(QPointF(tip_x, h / 2), 12, 12)
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
#  Task card
# ─────────────────────────────────────────────────────────────────────────────

class TaskCard(QFrame):
    """One animated task card in the history list."""

    def __init__(self, task: Dict, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.task = task
        self._progress_bar: Optional[GlowProgressBar] = None
        self._status_dot: Optional[PulsingDot] = None
        self._status_lbl: Optional[QLabel] = None
        self._summary_lbl: Optional[QLabel] = None
        self._err_lbl: Optional[QLabel] = None
        self._build()
        self._set_border_color()

    def _set_border_color(self):
        status = self.task.get("status", "pending")
        hex_c = STATUS_COLORS.get(status, C["text_muted"])
        r, g, b = int(hex_c[1:3], 16), int(hex_c[3:5], 16), int(hex_c[5:7], 16)
        self.setStyleSheet(
            f"QFrame#card {{ background-color: {C['bg_card']};"
            f"border: 1px solid rgba({r},{g},{b},80);"
            f"border-left: 3px solid {hex_c};"
            f"border-radius: 8px; }}"
        )

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        status = self.task.get("status", "pending")
        color_hex = STATUS_COLORS.get(status, C["text_muted"])

        # Header row
        header = QHBoxLayout()
        header.setSpacing(6)

        self._status_dot = PulsingDot(8)
        self._status_dot.set_color(color_hex)
        header.addWidget(self._status_dot)

        tid = self.task.get("task_id", "")[-8:]
        id_lbl = QLabel(f"#{tid}")
        id_lbl.setObjectName("muted")
        header.addWidget(id_lbl)

        self._status_lbl = QLabel(status.upper())
        self._status_lbl.setStyleSheet(
            f"color:{color_hex}; font-weight:700; font-size:10px;"
        )
        header.addStretch()
        header.addWidget(self._status_lbl)

        ts = self.task.get("start_time") or ""
        ts_str = ts[:19].replace("T", " ") if ts else ""
        if ts_str:
            ts_lbl = QLabel(ts_str)
            ts_lbl.setObjectName("muted")
            header.addSpacing(6)
            header.addWidget(ts_lbl)

        layout.addLayout(header)

        # Summary
        summary = self.task.get("summary", "")
        if not summary:
            summary = self.task.get("request", "")
        if summary:
            self._summary_lbl = QLabel(summary[:140])
            self._summary_lbl.setWordWrap(True)
            self._summary_lbl.setStyleSheet(
                f"color:{C['text_primary']}; font-size:12px;"
            )
            layout.addWidget(self._summary_lbl)

        # Progress bar
        total = self.task.get("total_steps", 0)
        done  = self.task.get("completed_steps", 0)
        if total > 0:
            self._progress_bar = GlowProgressBar()
            self._progress_bar.set_maximum(total)
            self._progress_bar.set_value(done)
            qc = QColor(color_hex)
            self._progress_bar.set_color(qc)
            layout.addWidget(self._progress_bar)

            step_lbl = QLabel(f"{done} / {total} steps")
            step_lbl.setObjectName("muted")
            layout.addWidget(step_lbl)

        # Error
        errors = self.task.get("error_log") or []
        if errors:
            err_text = " · ".join(str(e) for e in errors[:2])
            self._err_lbl = QLabel(f"⚠  {err_text[:120]}")
            self._err_lbl.setStyleSheet(
                f"color:{C['error']}; font-size:11px;"
            )
            self._err_lbl.setWordWrap(True)
            layout.addWidget(self._err_lbl)

    def update_task(self, task: Dict):
        """Surgically update existing widgets instead of rebuilding."""
        status_changed = task.get("status") != self.task.get("status")
        self.task = task

        status = task.get("status", "pending")
        color_hex = STATUS_COLORS.get(status, C["text_muted"])

        if self._status_dot:
            self._status_dot.set_color(color_hex)
        if self._status_lbl:
            self._status_lbl.setText(status.upper())
            self._status_lbl.setStyleSheet(
                f"color:{color_hex}; font-weight:700; font-size:10px;"
            )
        if status_changed:
            self._set_border_color()

        total = task.get("total_steps", 0)
        done  = task.get("completed_steps", 0)
        if self._progress_bar and total > 0:
            self._progress_bar.set_maximum(total)
            self._progress_bar.set_value(done)
            self._progress_bar.set_color(QColor(color_hex))

        summary = task.get("summary") or task.get("request") or ""
        if self._summary_lbl and summary:
            self._summary_lbl.setText(summary[:140])

        errors = task.get("error_log") or []
        if errors and self._err_lbl:
            err_text = " · ".join(str(e) for e in errors[:2])
            self._err_lbl.setText(f"⚠  {err_text[:120]}")


# ─────────────────────────────────────────────────────────────────────────────
#  Console widget
# ─────────────────────────────────────────────────────────────────────────────

class ConsoleWidget(QTextEdit):
    """Read-only live log console with coloured output."""

    _LEVEL_COLORS = {
        "info":    C["text_primary"],
        "success": C["success"],
        "warning": C["warning"],
        "error":   C["error"],
        "debug":   C["text_muted"],
        "step":    C["accent_cyan"],
        "system":  C["accent_purple"],
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumHeight(175)
        self.setStyleSheet(
            f"background-color: {C['bg_input']};"
            f"border: 1px solid {C['border']};"
            f"border-radius: 6px;"
            f"font-family: 'Cascadia Code', 'Consolas', monospace;"
            f"font-size: 11px;"
        )
        self._max_lines = 600

    def append_line(self, text: str, level: str = "info"):
        col = self._LEVEL_COLORS.get(level, C["text_primary"])
        ts  = datetime.now().strftime("%H:%M:%S")
        level_tag = f'<span style="color:{col};font-weight:600">[{level.upper()[:4]}]</span>'
        html = (
            f'<span style="color:{C["text_muted"]}">{ts}</span> '
            f'{level_tag} '
            f'<span style="color:{col}">{text}</span><br>'
        )
        self.moveCursor(QTextCursor.MoveOperation.End)
        self.insertHtml(html)
        self.ensureCursorVisible()

        doc = self.document()
        if doc.lineCount() > self._max_lines:
            cursor = self.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.movePosition(cursor.MoveOperation.Down,
                                cursor.MoveMode.KeepAnchor,
                                doc.lineCount() - self._max_lines)
            cursor.removeSelectedText()


# ─────────────────────────────────────────────────────────────────────────────
#  Typing indicator (bouncing dots when task is running)
# ─────────────────────────────────────────────────────────────────────────────

class TypingIndicator(QWidget):
    """Three bouncing dots shown when a task is processing."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 16)
        self._t = 0.0
        self._visible_flag = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)
        self.hide()

    def start(self):
        self._visible_flag = True
        self.show()

    def stop(self):
        self._visible_flag = False
        self.hide()

    def _tick(self):
        if self._visible_flag:
            self._t += 0.08
            self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(3):
            phase = self._t + i * 0.6
            y_off = 3.0 * math.sin(phase * 2.5)
            alpha = int(160 + 80 * math.sin(phase * 2.5))
            p.setBrush(QBrush(QColor(0, 212, 255, alpha)))
            p.drawEllipse(QPointF(6 + i * 14, 8 + y_off), 3, 3)
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
#  Main window
# ─────────────────────────────────────────────────────────────────────────────

class TaskWindow(QMainWindow):
    """
    Main NovaMind floating UI.

    Layout (top to bottom)
    ──────────────────────
    Title bar           — drag, status, controls
    Input area          — task text + Send button
    Quick actions       — preset buttons
    [Task Visualizer]   — 2-D animated orb view  ← NEW
    Task history        — scrollable task cards
    Console             — coloured live log
    Status bar          — system status + clock
    """

    task_submitted = pyqtSignal(str)

    def __init__(self, brain=None, game=None, parent=None):
        super().__init__(parent)
        self.brain = brain
        self.game  = game
        self._task_cards: Dict[str, TaskCard] = {}
        self._prev_active_count = 0

        self._setup_window()
        self._setup_tray()
        self._build_ui()
        self._setup_shortcuts()
        self._setup_timers()

    # ── window setup ────────────────────────────────────────────────────────

    def _setup_window(self):
        self.setWindowTitle("NovaMind")
        self.setMinimumSize(620, 780)
        self.resize(740, 900)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(APP_STYLE)

        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - 760, 30)

        self._drag_pos: Optional[QPoint] = None

    def _setup_tray(self):
        self._orb = FloatingOrb()
        self._orb.clicked.connect(self.toggle_visibility)

        self._tray = QSystemTrayIcon(self)
        self._tray.setToolTip("NovaMind")
        try:
            self._tray.setIcon(QIcon.fromTheme("computer"))
        except Exception:
            pass
        menu = QMenu()
        menu.addAction("Show / Hide", self.toggle_visibility)
        menu.addSeparator()
        menu.addAction("Quit", QApplication.instance().quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(
            lambda r: self.toggle_visibility()
            if r == QSystemTrayIcon.ActivationReason.Trigger else None
        )
        self._tray.show()

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        # Background
        self._bg = AnimatedBackground(self)
        self._bg.lower()

        central = QWidget(self)
        central.setObjectName("central")
        central.setStyleSheet(f"""
            #central {{
                background-color: transparent;
                border: 1px solid {C['border']};
                border-radius: 14px;
            }}
        """)
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_titlebar())
        root.addWidget(self._build_input_area())
        root.addWidget(self._build_quick_actions())
        root.addWidget(self._build_visualizer())
        root.addWidget(self._build_task_list(), 1)
        root.addWidget(self._build_console())
        root.addWidget(self._build_statusbar())

    def _build_titlebar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(48)
        bar.setStyleSheet(f"""
            background-color: rgba(13,20,34,240);
            border-bottom: 1px solid {C['border']};
            border-radius: 14px 14px 0 0;
        """)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 10, 0)
        layout.setSpacing(0)

        # Logo dot
        logo_dot = PulsingDot(10)
        logo_dot.set_color(C["accent_cyan"])
        layout.addWidget(logo_dot)
        layout.addSpacing(8)

        title = QLabel("NOVA<span style='color:#00d4ff'>MIND</span>")
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setStyleSheet(
            f"color:{C['text_primary']}; font-size:15px; font-weight:800;"
            f"letter-spacing: 2px;"
        )
        layout.addWidget(title)
        layout.addSpacing(14)

        self._typing_indicator = TypingIndicator()
        layout.addWidget(self._typing_indicator)

        layout.addStretch()

        self._status_dot = PulsingDot(8)
        self._status_dot.set_color(C["text_muted"])
        layout.addWidget(self._status_dot)
        layout.addSpacing(5)

        self._status_label = QLabel("Idle")
        self._status_label.setObjectName("muted")
        layout.addWidget(self._status_label)
        layout.addSpacing(14)

        for label, action in [
            ("─", self.showMinimized),
            ("□", self._toggle_max),
            ("✕", self._close_to_tray),
        ]:
            btn = QPushButton(label)
            btn.setFixedSize(30, 30)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background:transparent; border:none;
                    color:{C['text_muted']}; font-size:13px;
                    border-radius: 4px;
                }}
                QPushButton:hover {{
                    background:{C['bg_card']};
                    color:{C['text_primary']};
                }}
            """)
            btn.clicked.connect(action)
            layout.addWidget(btn)

        bar.mousePressEvent   = self._title_mouse_press
        bar.mouseMoveEvent    = self._title_mouse_move
        bar.mouseReleaseEvent = self._title_mouse_release
        return bar

    def _build_input_area(self) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet(
            f"background-color: rgba(13,20,34,220);"
            f"border-bottom: 1px solid {C['border']};"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        label = QLabel("What would you like me to do?")
        label.setObjectName("heading")
        layout.addWidget(label)

        row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText(
            'e.g. "Draw a blue car in MS Paint" · "Search Python tutorials" · "Show CPU stats"'
        )
        self._input.setMinimumHeight(42)
        self._input.returnPressed.connect(self._submit_task)
        row.addWidget(self._input, 1)

        self._send_btn = QPushButton("Send")
        self._send_btn.setObjectName("primary")
        self._send_btn.setFixedSize(76, 42)
        self._send_btn.clicked.connect(self._submit_task)
        row.addWidget(self._send_btn)
        layout.addLayout(row)
        return frame

    def _build_quick_actions(self) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet(
            f"background-color: rgba(10,16,32,220);"
            f"border-bottom: 1px solid {C['border']};"
        )
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 6, 14, 6)
        layout.setSpacing(5)

        quick = [
            ("🖌 Draw Car",     "Draw a blue sports car in MS Paint"),
            ("📊 CPU Stats",   "Show current CPU, RAM and disk usage"),
            ("🌐 Web Search",  "Search the web for "),
            ("📁 List Files",  "List files in my Downloads folder"),
            ("⚡ Run Script",  "Write and run a Python hello world script"),
            ("📸 Screenshot",  "Take a screenshot of the current screen"),
        ]
        for label, text in quick:
            btn = QPushButton(label)
            btn.setFixedHeight(26)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(20,30,50,200);
                    border: 1px solid {C['border']};
                    border-radius: 4px;
                    padding: 0 9px;
                    color: {C['text_secondary']};
                    font-size: 10px;
                }}
                QPushButton:hover {{
                    background: {C['accent_blue']};
                    color: white;
                    border-color: {C['accent_blue']};
                }}
            """)
            btn.clicked.connect(lambda _, t=text: self._fill_input(t))
            layout.addWidget(btn)
        layout.addStretch()
        return frame

    def _build_visualizer(self) -> QWidget:
        """Embed the 2-D animated task visualiser."""
        frame = QFrame()
        frame.setStyleSheet(
            f"background-color: rgba(8,14,28,200);"
            f"border-bottom: 1px solid {C['border']};"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Section header
        hdr = QWidget()
        hdr.setFixedHeight(26)
        hdr.setStyleSheet(f"background: rgba(13,20,34,180);")
        hdr_lay = QHBoxLayout(hdr)
        hdr_lay.setContentsMargins(14, 0, 14, 0)
        lbl = QLabel("◈  TASK VISUALIZER")
        lbl.setStyleSheet(
            f"color:{C['accent_cyan']}; font-size:10px; font-weight:700;"
            f"letter-spacing:2px;"
        )
        hdr_lay.addWidget(lbl)
        hdr_lay.addStretch()
        toggle = QPushButton("Hide")
        toggle.setFixedSize(36, 18)
        toggle.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none;
                color: {C['text_muted']}; font-size: 9px;
            }}
            QPushButton:hover {{ color: {C['text_primary']}; }}
        """)
        layout.addWidget(hdr)

        self._visualizer = TaskVisualizer()
        layout.addWidget(self._visualizer)

        def _toggle_viz():
            if self._visualizer.isVisible():
                self._visualizer.hide()
                toggle.setText("Show")
            else:
                self._visualizer.show()
                toggle.setText("Hide")

        toggle.clicked.connect(_toggle_viz)
        hdr_lay.addWidget(toggle)
        return frame

    def _build_task_list(self) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet(f"background-color: rgba(7,11,20,180);")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 0)
        layout.setSpacing(6)

        hdr = QHBoxLayout()
        hdr_lbl = QLabel("Task History")
        hdr_lbl.setObjectName("heading")
        hdr_lbl.setStyleSheet(
            f"color:{C['text_primary']}; font-size:13px; font-weight:700;"
        )
        self._task_count_lbl = QLabel("0 tasks")
        self._task_count_lbl.setObjectName("muted")
        hdr.addWidget(hdr_lbl)
        hdr.addStretch()
        hdr.addWidget(self._task_count_lbl)
        layout.addLayout(hdr)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("background: transparent; border: none;")

        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 4, 0)
        self._list_layout.setSpacing(6)
        self._list_layout.addStretch()

        self._scroll.setWidget(self._list_widget)
        layout.addWidget(self._scroll)
        return frame

    def _build_console(self) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet(
            f"background-color: rgba(7,11,20,200);"
            f"border-top: 1px solid {C['border']};"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 6, 14, 6)
        layout.setSpacing(4)

        hdr = QHBoxLayout()
        lbl = QLabel("Console")
        lbl.setStyleSheet(
            f"color:{C['text_muted']}; font-size:10px;"
            f"letter-spacing:1px; font-weight:600;"
        )
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedSize(44, 18)
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none;
                color: {C['text_muted']}; font-size: 9px;
            }}
            QPushButton:hover {{ color: {C['text_primary']}; }}
        """)
        clear_btn.clicked.connect(lambda: self._console.clear())
        hdr.addWidget(lbl)
        hdr.addStretch()
        hdr.addWidget(clear_btn)
        layout.addLayout(hdr)

        self._console = ConsoleWidget()
        layout.addWidget(self._console)
        return frame

    def _build_statusbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(28)
        bar.setStyleSheet(f"""
            background-color: rgba(13,20,34,240);
            border-top: 1px solid {C['border']};
            border-radius: 0 0 14px 14px;
        """)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 0, 14, 0)

        self._statusbar_label = QLabel("Ready")
        self._statusbar_label.setObjectName("muted")
        layout.addWidget(self._statusbar_label)
        layout.addStretch()

        self._clock_lbl = QLabel(datetime.now().strftime("%H:%M"))
        self._clock_lbl.setObjectName("muted")
        layout.addWidget(self._clock_lbl)
        return bar

    # ── shortcuts & timers ──────────────────────────────────────────────────

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+Return"), self).activated.connect(self._submit_task)
        QShortcut(QKeySequence("Escape"),      self).activated.connect(self._close_to_tray)
        QShortcut(QKeySequence("Ctrl+L"),      self).activated.connect(self._console.clear)

    def _setup_timers(self):
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._periodic_refresh)
        self._refresh_timer.start(1200)

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(15_000)

    # ── public API ───────────────────────────────────────────────────────────

    def update_task_list(self, tasks: List[Optional[Dict]]):
        """Refresh task cards and visualiser with live Brain data."""
        if tasks is None:
            return

        clean = [t for t in tasks if t]
        active_count = sum(
            1 for t in clean if t.get("status") in ("running", "retrying")
        )

        for task in clean:
            tid    = task.get("task_id", "")
            status = task.get("status", "pending")

            if tid in self._task_cards:
                self._task_cards[tid].update_task(task)
            else:
                card = TaskCard(task)
                self._task_cards[tid] = card
                pos = self._list_layout.count() - 1
                self._list_layout.insertWidget(pos, card)

                # Sparkle on success
                if status in ("success", "done"):
                    self._visualizer.add_sparkle(
                        self._visualizer.width() / 2,
                        self._visualizer.height() / 2,
                        QColor(C["success"]),
                    )

        total = len(clean)
        self._task_count_lbl.setText(
            f"{total} task{'s' if total != 1 else ''}"
        )
        self._orb.set_task_count(active_count)
        self._visualizer.update_tasks(clean)

        if active_count > 0:
            self._set_status("Running …", C["accent_cyan"])
            self._typing_indicator.start()
            self._orb.set_color(C["accent_cyan"])
        else:
            self._set_status("Idle", C["text_muted"])
            self._typing_indicator.stop()
            has_failed = any(
                t.get("status") == "failed" for t in clean
            )
            self._orb.set_color(
                C["error"] if has_failed else C["success"]
                if total > 0 else C["text_muted"]
            )

        self._prev_active_count = active_count

    def start_game_loop(self):
        """
        Legacy: game loop was managed by a QTimer calling game.step().
        Now game runs in its own subprocess (GameProcessManager) with its own
        loop — no QTimer stepping needed. Method kept for API compatibility.
        """
        _has_step = {True: lambda: (
            setattr(self, "_game_timer", QTimer(self)),
            self._game_timer.timeout.connect(self.game.step),
            self._game_timer.start(16),
            self.log_console("Engine loop started (60Hz)", "system"),
        )}
        action = _has_step.get(bool(self.game and hasattr(self.game, "step")))
        action and action()
        _no_step = {True: lambda: self.log_console(
            "Game runs in subprocess — no QTimer step needed", "system"
        )}
        no_step = _no_step.get(bool(self.game and not hasattr(self.game, "step")))
        no_step and no_step()

    def log_console(self, message: str, level: str = "info"):

        self._console.append_line(message, level)

    # ── task submission ──────────────────────────────────────────────────────

    def _submit_task(self):
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self.log_console(f"Submitted: {text}", "step")
        self._set_status("Processing …", C["accent_blue"])
        self._typing_indicator.start()
        self.task_submitted.emit(text)

    def _fill_input(self, text: str):
        self._input.setText(text)
        self._input.setFocus()

    # ── periodic refresh ─────────────────────────────────────────────────────

    def _periodic_refresh(self):
        if self.brain:
            tasks = self.brain.get_all_tasks()
            self.update_task_list(tasks)

    def _update_clock(self):
        self._clock_lbl.setText(datetime.now().strftime("%H:%M"))

    # ── window helpers ───────────────────────────────────────────────────────

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._bg.setGeometry(self.rect())

    def _set_status(self, text: str, color_hex: str):
        self._status_label.setText(text)
        self._status_dot.set_color(color_hex)
        self._statusbar_label.setText(text)

    def _close_to_tray(self):
        self.hide()
        self._orb.show()

    def _toggle_max(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def toggle_visibility(self):
        if self.isVisible():
            self._close_to_tray()
        else:
            self._orb.hide()
            self.show()
            self.raise_()
            self.activateWindow()

    # Title-bar drag
    def _title_mouse_press(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (
                e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )

    def _title_mouse_move(self, e):
        if self._drag_pos and e.buttons() == Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def _title_mouse_release(self, _e):
        self._drag_pos = None

    def closeEvent(self, e):
        e.ignore()
        self._close_to_tray()
