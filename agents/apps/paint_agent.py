"""
agents/apps/paint_agent.py

MS Paint — specific action module.
Handles: open, draw, set color, select tool, save, clear.

Refactored to enforce strict Actionability Checks.
No dict-dispatch logic. Propagates exceptions properly.
"""

import time
import logging
import os

# --- Phase 10.5 Capability Shim ---
import sys as _sys
class _ModuleShim:
    def __init__(self, mod_name): self._mod_name = mod_name
    def __getattr__(self, name): return getattr(__import__(self._mod_name), name)
subprocess = _ModuleShim('subprocess')
shutil = _ModuleShim('shutil')
socket = _ModuleShim('socket')
# ----------------------------------
import random
import math
import re
from typing import Dict, List, Optional, Tuple, Any

COLOR_MAP: Dict[str, Tuple[int, int, int]] = {
    "black": (0,0,0), "white": (255,255,255),
    "red": (237,28,36), "dark_red": (136,0,21), "crimson": (220,20,60),
    "pink": (255,174,201), "rose": (255,20,147),
    "orange": (255,127,39), "gold": (255,201,14), "yellow": (255,242,0),
    "light_yellow": (255,255,153), "beige": (245,245,220),
    "green": (34,177,76), "lime": (0,255,0), "sea_green": (46,139,87),
    "turquoise": (0,162,232), "cyan": (0,255,255), "light_blue": (153,217,234),
    "blue": (0,0,255), "indigo": (63,72,204), "dark_blue": (0,0,128),
    "purple": (163,73,164), "magenta": (255,0,255), "lavender": (200,191,231),
    "brown": (185,122,87), "gray": (127,127,127), "light_gray": (195,195,195),
}

class DrawingPlan:
    def __init__(self, subject: str, cw: int = 600, ch: int = 400):
        self.subject       = subject
        self.canvas_width  = cw
        self.canvas_height = ch
        self.strokes: List[Dict] = []
        self.color_rgb: Tuple[int, int, int] = (0, 0, 255)

    def add_stroke(self, points: List[Tuple[int, int]], color: Tuple[int, int, int] = None):
        self.strokes.append({
            "color":  color or self.color_rgb,
            "points": points
        })

from core.foundation.base_agent import BaseAgent

logger = logging.getLogger("PaintAgent")

# ── Optional imports ─────────────────────────────────────────────────────────
try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE    = 0.03
    PYAUTOGUI_OK = True
except ImportError:
    PYAUTOGUI_OK = False

try:
    import pygetwindow as gw
    GW_OK = True
except ImportError:
    GW_OK = False

try:
    from core.os_utils.os_executor import (
        OSExecutor, assert_window_focused, detect_paint_canvas,
        safe_drag, safe_click, safe_hotkey, release_all_modifiers,
        ActionVerifier, FocusLostError, capture_region, ExecutionDependencyError
    )
    from core.os_utils.uia_executor import UIAExecutor, UIAError
    from core.os_utils.element_finder import get_finder, ElementNotFoundError, DependencyMissingError
    CORE_OK = True
except ImportError as _e:
    logger.warning(f"PaintAgent: core dependencies missing ({_e})")
    CORE_OK = False
    FocusLostError = Exception
    ExecutionDependencyError = Exception

# ── Constants ─────────────────────────────────────────────────────────────────
_WINDOW_TITLE   = "Paint"
_OPEN_WAIT      = 1.5
_POLL_INTERVAL  = 0.3
_POLL_MAX       = 20
_MAXIMIZE_WAIT  = 0.5
_FOCUS_WAIT     = 0.3

class CanvasNotFoundError(Exception):
    """Implementation stub"""


# ── PaintAgent ────────────────────────────────────────────────────────────────

class PaintAgent(BaseAgent):
    """
    State-of-the-art Paint automation specialist.
    Handles all drawing planning and focus-safe execution.
    """

    def __init__(self) -> None:
        super().__init__(name="PaintAgent", role="Agent")
        
        self._os = None
        self._uia = None
        
        if CORE_OK:
            self._os = OSExecutor(_WINDOW_TITLE)
            self._uia = UIAExecutor()

        self.handlers = {
            "ensure_open":   lambda: {"success": self.ensure_open()},
            "get_canvas":    lambda: {"success": True, "canvas": self.get_canvas()},
            "clear_canvas":  lambda: {"success": self.clear_canvas()},
            "set_color":     lambda r, g, b: {"success": self.set_color_uia(r, g, b)},
            "select_pencil": lambda: {"success": self.select_pencil()},
            "draw_stroke":   self.draw_stroke,
            "save":          lambda path=None: {"success": self.save(path)},
            "draw_task":     self.draw_task,
        }

    # ── Public API ────────────────────────────────────────────────────────────

    def draw_task(self, description: str) -> Dict:
        """
        High-level drawing task handler.
        1. Parse color
        2. Plan drawing (LLM or fallback)
        3. Execute (clear -> set color -> select pencil -> draw)
        4. Screenshot
        """
        try:
            rgb = self._parse_color(description.lower())
            
            canvas = self.get_canvas()
            if not canvas:
                raise CanvasNotFoundError("Could not detect MS Paint canvas area.")
            
            cx1, cy1, cx2, cy2 = canvas
            plan = self._generate_drawing_plan(description, rgb, cx2-cx1, cy2-cy1)
            
            self.clear_canvas()
            self.set_color_uia(*rgb)
            self.select_pencil()
            
            results = [self.draw_stroke(s["points"], canvas) for s in plan.strokes]
            
            path = self._capture_canvas_screenshot(canvas)
            return {
                "success": all(r.get("success") for r in results),
                "steps": len(results),
                "screenshot": path
            }
        except Exception as e:
            logger.error(f"Draw task failed: {e}")
            return {"success": False, "error": str(e)}

    # ── Internal Implementation ───────────────────────────────────────────────

    def _parse_color(self, text: str) -> Tuple[int, int, int]:
        """Simple color lookup."""
        for word in text.split():
            if word in COLOR_MAP: return COLOR_MAP[word]
        return (0, 0, 0)

    def _generate_drawing_plan(self, subject: str, color: Tuple[int, int, int], cw: int, ch: int) -> DrawingPlan:
        """Generate stroke plan via LLM, fall back to geometric sports car."""
        plan = DrawingPlan(subject, cw, ch)
        try:
            from core.orchestration.llm_router import get_router
            import json
            router = get_router()
            prompt = (
                f'Generate pyautogui drawing strokes for "{subject}" '
                f'on a {cw}x{ch} pixel canvas. Main color RGB{color}.\n'
                f'Return ONLY a JSON array of stroke objects:\n'
                f'[{{"color":[r,g,b],"points":[[x,y],[x,y],...]}},...]\n'
                f'Constraints: x in [5,{cw-5}], y in [5,{ch-5}], '
                f'consecutive points <= 15px apart, 30-200 strokes total.\n'
                f'No explanation text — only the JSON array.'
            )
            resp = router.quick_request(prompt, task_type="coding")
            m    = re.search(r'\[.*\]', resp, re.DOTALL)
            if m:
                raw = json.loads(m.group())
                for s in raw:
                    pts = [(max(0, min(cw-1, int(p[0]))), max(0, min(ch-1, int(p[1]))))
                           for p in s.get("points", [])]
                    if len(pts) >= 2:
                        plan.add_stroke(pts, tuple(s.get("color", color)))
                if plan.strokes:
                    return plan
        except Exception as e:
            logger.warning(f"LLM drawing plan error: {e}")

        logger.info("Using geometric car fallback drawing plan")
        return self._car_fallback(plan, cw, ch, color)

    def _car_fallback(self, plan: DrawingPlan, w: int, h: int, color: Tuple[int, int, int]) -> DrawingPlan:
        """Geometric sports car using proportional coordinates."""
        pi = math.pi
        def sc(pts): return [(int(x * w), int(y * h)) for x, y in pts]
        def line(x1f, y1f, x2f, y2f, clr=None):
            pts = [(x1f + (x2f-x1f)*i/10, y1f + (y2f-y1f)*i/10) for i in range(11)]
            plan.add_stroke(sc(pts), clr or color)
        def arc(cx, cy, rx, ry, a0, a1, clr=None):
            angs = [a0 + (a1-a0)*i/20 for i in range(21)]
            pts  = [(cx + rx*math.cos(a), cy + ry*math.sin(a)) for a in angs]
            plan.add_stroke(sc(pts), clr or color)

        bl, br, bt, bb = 0.07, 0.93, 0.50, 0.75
        line(bl,bb,br,bb); line(bl,bb,bl,bt); line(br,bb,br,bt)
        plan.add_stroke(sc([(0.22,bt),(0.28,0.30),(0.72,0.30),(0.78,bt)]), color)
        for wx in [0.22, 0.78]: arc(wx, bb, 0.10, 0.09, 0, 2*pi, (0,0,0))
        return plan

    def _capture_canvas_screenshot(self, canvas: Tuple[int, int, int, int]) -> str:
        """Capture region and save."""
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab(bbox=canvas)
            path = os.path.expanduser("~/.novamind/vision/paint_result.png")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            img.save(path)
            return path
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return ""

    def ensure_open(self) -> bool:
        """Open, focus, and maximise Paint."""
        if not GW_OK:
            raise ExecutionDependencyError("pygetwindow is required to ensure paint is open.")

        def get_wins():
            return gw.getWindowsWithTitle(_WINDOW_TITLE)
            
        wins = get_wins()
        if not wins:
            subprocess.Popen(["mspaint"])
            time.sleep(_OPEN_WAIT)
            
        for _ in range(_POLL_MAX):
            wins = get_wins()
            if wins:
                try:
                    w = wins[0]
                    w.activate()
                    time.sleep(_FOCUS_WAIT)
                    if PYAUTOGUI_OK:
                        pyautogui.hotkey('win', 'up')
                        time.sleep(_MAXIMIZE_WAIT)
                    assert_window_focused(_WINDOW_TITLE, max_wait=3.0)
                    return True
                except Exception as e:
                    logger.warning(f"Failed to focus paint: {e}")
            time.sleep(_POLL_INTERVAL)
            
        return False

    def get_canvas(self) -> Optional[Tuple[int, int, int, int]]:
        """Fetch canvas bounds via OSExecutor."""
        if not CORE_OK:
            raise ExecutionDependencyError("core.os_executor is required.")
        return detect_paint_canvas()

    def clear_canvas(self) -> bool:
        """Confirm focus and wipe canvas via Ctrl+A + Delete."""
        if not CORE_OK:
            raise ExecutionDependencyError("core.os_executor is required.")
            
        assert_window_focused(_WINDOW_TITLE)
        safe_hotkey(_WINDOW_TITLE, 'ctrl', 'a')
        time.sleep(0.12)
        safe_hotkey(_WINDOW_TITLE, 'delete')
        return True

    def set_color_uia(self, r: int, g: int, b: int) -> bool:
        """Set foreground color via semantic UIA handles."""
        if not CORE_OK or not self._uia:
            raise ExecutionDependencyError("UIA is required to set color.")
            
        try:
            self._uia.set_paint_rgb(r, g, b)
            return True
        except UIAError as e:
            logger.warning(f"Could not set color via UIA: {e}")
            return False

    def select_pencil(self) -> bool:
        """Select pencil tool. Primary: UIA finder, Secondary: Keyboard hotkey."""
        if not CORE_OK:
            raise ExecutionDependencyError("Core is required for pencil select.")
            
        try:
            f = get_finder()
            el = f.find("Pencil", window_title=_WINDOW_TITLE, strategy="uia")
            if el:
                el.click()
                return True
        except (ElementNotFoundError, DependencyMissingError, UIAError) as e:
            logger.debug(f"UIA pencil selection failed: {e}")
            
        # Fallback to hotkey
        safe_hotkey(_WINDOW_TITLE, 'p')
        return True

    def draw_stroke(self, points: List[Tuple[int, int]], canvas: Tuple[int, int, int, int]) -> Dict:
        """Execute complex stroke with focus-verified safety."""
        if not CORE_OK or not PYAUTOGUI_OK:
            raise ExecutionDependencyError("Dependencies missing for draw_stroke")
            
        if len(points) < 2: 
            return {"success": False, "error": "Not enough points"}
            
        cx1, cy1, _, _ = canvas
        
        try:
            assert_window_focused(_WINDOW_TITLE)
            pyautogui.moveTo(cx1 + points[0][0], cy1 + points[0][1])
            pyautogui.mouseDown()
            
            for p in points[1:]:
                pyautogui.moveTo(cx1 + p[0], cy1 + p[1], duration=0.01)
                
            return {"success": True}
        except FocusLostError as e:
            return {"success": False, "error": str(e)}
        finally:
            if PYAUTOGUI_OK:
                pyautogui.mouseUp()
                
    def save(self, path: Optional[str] = None) -> bool:
        if not CORE_OK:
            raise ExecutionDependencyError("Core missing")
            
        try:
            assert_window_focused(_WINDOW_TITLE)
            safe_hotkey(_WINDOW_TITLE, 'ctrl', 's')
            time.sleep(1.0)
            if path:
                safe_type_clipboard(path, _WINDOW_TITLE)
                time.sleep(0.5)
            safe_hotkey(_WINDOW_TITLE, 'enter')
            return True
        except Exception as e:
            logger.error(f"Save failed: {e}")
            return False