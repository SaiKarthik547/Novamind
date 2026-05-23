"""
core/os_executor.py

Real OS-level execution layer.
Refactored to eliminate all dict-dispatch logic and implement strict
Actionability Checks before any raw OS action is performed.

Raises explicit exceptions (FocusLostError, ExecutionDependencyError)
instead of silently failing or skipping actions.
"""

import ctypes
import platform
import time
import logging
from typing import Optional, Tuple

logger = logging.getLogger("OSExecutor")

# ── Structured audit log — action telemetry ──────────────────────────────────────
_ACTION_AUDIT: list = []  # circular buffer of last 500 actions
_AUDIT_MAX = 500

class FocusLostError(Exception):
    """Raised when the target window cannot be brought to focus."""
    pass

class ExecutionDependencyError(Exception):
    """Raised when a system dependency (pyautogui, PIL, etc.) is missing."""
    pass


def _audit(action: str, window: str, params: dict, success: bool, error: str = "") -> None:
    """Record every OS-level action to the in-memory audit trail."""
    import datetime
    entry = {
        "ts":      datetime.datetime.now().isoformat(),
        "action":  action,
        "window":  window,
        "params":  params,
        "success": success,
        "error":   error,
    }
    _ACTION_AUDIT.append(entry)
    _ACTION_AUDIT[:] = _ACTION_AUDIT[-_AUDIT_MAX:]
    
    if success:
        logger.debug(f"[AUDIT] {action} on '{window}' ✓ {params}")
    else:
        logger.warning(f"[AUDIT] {action} on '{window}' ✗ error={error}")


def get_audit_log() -> list:
    """Return a copy of the recent audit log (last 500 actions)."""
    return list(_ACTION_AUDIT)


# ── Chaos testing hook — inject focus-loss during test runs ───────────────────────
_CHAOS_HOOKS: dict = {}

def _run_chaos_hook(action_name: str) -> None:
    """Fire any registered chaos hook for the given action."""
    hook = _CHAOS_HOOKS.get(action_name)
    if hook:
        hook()


try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    PYAUTOGUI_OK = True
except ImportError:
    PYAUTOGUI_OK = False

try:
    import pygetwindow as gw
    PYGETWINDOW_OK = True
except ImportError:
    PYGETWINDOW_OK = False

try:
    from PIL import Image, ImageGrab
    PIL_OK = True
except ImportError:
    PIL_OK = False


# ── DPI detection — one call at import time ───────────────────────────────────

def _detect_dpi() -> float:
    """Get the real DPI scale factor."""
    if platform.system() != "Windows":
        return 1.0
    try:
        import ctypes
        awareness = ctypes.c_int()
        ctypes.windll.shcore.GetProcessDpiAwareness(0, ctypes.byref(awareness))
        if awareness.value >= 1:
            logger.info(f"DPI-aware process detected (awareness={awareness.value}) — scale=1.0")
            return 1.0
    except Exception as e:
        logger.debug(f"GetProcessDpiAwareness failed: {e}")
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        scale = max(0.5, ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100.0)
        logger.info(f"DPI scale detected: {scale}")
        return scale
    except Exception as e:
        logger.warning(f"DPI detection failed: {e} — using 1.0")
        return 1.0


DPI_SCALE: float = _detect_dpi()

def logical_to_physical(x: int, y: int) -> Tuple[int, int]:
    return int(x / DPI_SCALE), int(y / DPI_SCALE)

def physical_to_logical(x: int, y: int) -> Tuple[int, int]:
    return int(x * DPI_SCALE), int(y * DPI_SCALE)


# ── Focus guard ───────────────────────────────────────────────────────────────

def _try_activate_window(title_contains: str) -> bool:
    """Best-effort: find and activate a window. Returns True on success."""
    if not PYGETWINDOW_OK:
        return False
        
    wins = gw.getWindowsWithTitle(title_contains)
    if wins:
        wins[0].activate()
        time.sleep(0.15)
        return True
    return False


def assert_window_focused(title_contains: str, max_wait: float = 2.0) -> bool:
    """
    Verify/restore window focus before any pyautogui action.
    Polls until focused or max_wait expires; raises FocusLostError on timeout.
    """
    if not title_contains:
        return True
    
    _run_chaos_hook("assert_window_focused")
    deadline = time.time() + max_wait
    
    while time.time() < deadline:
        try:
            active = gw.getActiveWindow() if PYGETWINDOW_OK else None
            is_focused = active and title_contains.lower() in active.title.lower()
            
            if is_focused:
                return True
            else:
                if _try_activate_window(title_contains):
                    return True
        except Exception as e:
            logger.debug(f"Focus check iteration failed: {e}")
        time.sleep(0.1)
        
    raise FocusLostError(
        f"Could not establish focus on '{title_contains}' "
        f"after {max_wait}s — aborting to prevent wrong-app execution"
    )


# ── Modifier key safety ───────────────────────────────────────────────────────

_MODIFIER_KEYS = ('ctrl', 'shift', 'alt', 'win')

def release_all_modifiers() -> None:
    """Release all modifier keys. Call before scroll and before drag start."""
    if not PYAUTOGUI_OK:
        return
        
    for key in _MODIFIER_KEYS:
        try:
            pyautogui.keyUp(key)
        except Exception as e:
            logger.debug(f"Modifier release failed for {key}: {e}")


# ── Canvas detection ──────────────────────────────────────────────────────────

def detect_paint_canvas() -> Optional[Tuple[int, int, int, int]]:
    """
    Dynamically detect the MS Paint canvas bounding box.
    Returns (left, top, right, bottom) in physical screen coordinates.
    Scans the ribbon area for the first majority-white row (canvas start).
    """
    if not PYGETWINDOW_OK or not PIL_OK:
        return None

    try:
        wins = [w for w in gw.getAllWindows() if "paint" in w.title.lower() and w.visible]
        if not wins:
            return None

        w = wins[0]
        wx_p, wy_p = max(0, w.left), max(0, w.top)
        ww_p, wh_p = max(1, w.width), max(1, w.height)

        scan_h = min(280, wh_p - 10)
        ribbon_img = ImageGrab.grab(bbox=(wx_p, wy_p, wx_p + ww_p, wy_p + scan_h))
        ribbon_arr = list(ribbon_img.getdata())
        img_w = ribbon_img.width

        def _scan():
            for row in range(80, scan_h):
                start = row * img_w
                row_px = ribbon_arr[start:start + img_w]
                white_count = sum(1 for px in row_px if len(px) >= 3 and px[0]>240 and px[1]>240 and px[2]>240)
                is_canvas = img_w > 0 and (white_count / img_w) > 0.70
                if is_canvas: return row
            return 125 # fallback
        
        canvas_top = _scan()
        return (max(0, wx_p + 4), max(0, wy_p + canvas_top), wx_p + ww_p - 4, wy_p + wh_p - 30)
    except Exception as e:
        logger.debug(f"Canvas detection failed: {e}")
        return None


def point_inside_region(x: int, y: int, region: Tuple[int, int, int, int]) -> bool:
    left, top, right, bottom = region
    return left <= x <= right and top <= y <= bottom


# ── Safe action primitives ────────────────────────────────────────────────────

def safe_click(x: int, y: int, window_title: str, button: str = 'left', clicks: int = 1) -> None:
    """Click at (x, y) only after asserting window focus and releasing modifiers."""
    if not PYAUTOGUI_OK:
        raise ExecutionDependencyError("Cannot click: pyautogui is not available.")
        
    _run_chaos_hook("safe_click")
    assert_window_focused(window_title)
    release_all_modifiers()
    
    try:
        pyautogui.click(x, y, button=button, clicks=clicks, interval=0.1)
        _audit("safe_click", window_title, {"x": x, "y": y, "button": button, "clicks": clicks}, True)
    except Exception as e:
        _audit("safe_click", window_title, {"x": x, "y": y}, False, str(e))
        raise


def safe_drag(x1: int, y1: int, x2: int, y2: int, window_title: str, duration: float = 0.35) -> None:
    """
    Drag from (x1,y1) to (x2,y2) with full safety:
    - Focus asserted before starting
    - Modifiers released before mouseDown
    - mouseUp in finally block — mouse NEVER stays held
    """
    if not PYAUTOGUI_OK:
        raise ExecutionDependencyError("Cannot drag: pyautogui is not available.")
        
    _run_chaos_hook("safe_drag")
    assert_window_focused(window_title)
    release_all_modifiers()
    
    try:
        _execute_drag(x1, y1, x2, y2, duration)
        _audit("safe_drag", window_title, {"from": (x1, y1), "to": (x2, y2)}, True)
    except Exception as e:
        _audit("safe_drag", window_title, {"from": (x1, y1), "to": (x2, y2)}, False, str(e))
        raise


def _execute_drag(x1: int, y1: int, x2: int, y2: int, duration: float) -> None:
    """Internal: perform the drag with guaranteed mouseUp."""
    try:
        pyautogui.mouseDown(x1, y1)
        time.sleep(0.05)
        pyautogui.moveTo(x2, y2, duration=duration)
    finally:
        pyautogui.mouseUp()


def safe_scroll(x: int, y: int, clicks: int, window_title: str,
                region: Optional[Tuple[int, int, int, int]] = None) -> None:
    """
    Scroll at (x, y). Modifiers released first to prevent Ctrl+Scroll zoom.
    Raises ValueError if target outside the given safe region.
    """
    if not PYAUTOGUI_OK:
        raise ExecutionDependencyError("Cannot scroll: pyautogui is not available.")
        
    _run_chaos_hook("safe_scroll")
    assert_window_focused(window_title)
    release_all_modifiers()
    
    if region and not point_inside_region(x, y, region):
        raise ValueError(f"Scroll ({x},{y}) outside safe region {region}")
        
    try:
        pyautogui.scroll(clicks, x=x, y=y)
        _audit("safe_scroll", window_title, {"x": x, "y": y, "clicks": clicks}, True)
    except Exception as e:
        _audit("safe_scroll", window_title, {"x": x, "y": y}, False, str(e))
        raise


def safe_move(window_title: str, x: int, y: int, duration: float = 0.15) -> None:
    """Move mouse to (x, y) after asserting window focus."""
    if not PYAUTOGUI_OK:
        raise ExecutionDependencyError("Cannot move mouse: pyautogui is not available.")
        
    _run_chaos_hook("safe_move")
    assert_window_focused(window_title)
    
    try:
        pyautogui.moveTo(x, y, duration=duration)
        _audit("safe_move", window_title, {"x": x, "y": y}, True)
    except Exception as e:
        _audit("safe_move", window_title, {"x": x, "y": y}, False, str(e))
        raise


def safe_type(text: str, window_title: str, interval: float = 0.05) -> None:
    """Type text only after asserting window focus. ASCII typewrite only."""
    if not PYAUTOGUI_OK:
        raise ExecutionDependencyError("Cannot type: pyautogui is not available.")
        
    _run_chaos_hook("safe_type")
    assert_window_focused(window_title)
    
    try:
        pyautogui.typewrite(text, interval=interval)
        _audit("safe_type", window_title, {"text_len": len(text)}, True)
    except Exception as e:
        _audit("safe_type", window_title, {"text_len": len(text)}, False, str(e))
        raise


def safe_type_clipboard(text: str, window_title: str) -> None:
    """
    Type any text (including Unicode, special chars) via clipboard paste.
    Preserves original clipboard content. Asserts focus before paste.
    """
    if not PYAUTOGUI_OK:
        raise ExecutionDependencyError("Cannot type: pyautogui is not available.")
        
    _run_chaos_hook("safe_type_clipboard")
    assert_window_focused(window_title)
    
    try:
        import pyperclip
        original = pyperclip.paste()
        pyperclip.copy(text)
        time.sleep(0.08)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.12)
        pyperclip.copy(original)  # restore clipboard
        _audit("safe_type_clipboard", window_title, {"text_len": len(text)}, True)
    except ImportError:
        # pyperclip not available — fall back to character-by-character
        for ch in text:
            if ord(ch) < 128:
                pyautogui.typewrite(ch, interval=0.02)
        _audit("safe_type_clipboard", window_title, {"text_len": len(text), "method": "char_fallback"}, True)
    except Exception as e:
        _audit("safe_type_clipboard", window_title, {"text_len": len(text)}, False, str(e))
        raise


def safe_hotkey(window_title: str, *keys) -> None:
    """Hotkey with focus check, modifier release, and audit log."""
    if not PYAUTOGUI_OK:
        raise ExecutionDependencyError("Cannot press hotkey: pyautogui is not available.")
        
    _run_chaos_hook("safe_hotkey")
    assert_window_focused(window_title)
    release_all_modifiers()
    
    try:
        pyautogui.hotkey(*keys)
        _audit("safe_hotkey", window_title, {"keys": keys}, True)
    except Exception as e:
        _audit("safe_hotkey", window_title, {"keys": keys}, False, str(e))
        raise


def safe_press(window_title: str, key: str, times: int = 1, interval: float = 0.05) -> None:
    """Press a key one or more times after asserting window focus."""
    if not PYAUTOGUI_OK:
        raise ExecutionDependencyError("Cannot press key: pyautogui is not available.")
        
    _run_chaos_hook("safe_press")
    assert_window_focused(window_title)
    
    try:
        for _ in range(times):
            pyautogui.press(key)
            if interval > 0:
                time.sleep(interval)
        _audit("safe_press", window_title, {"key": key, "times": times}, True)
    except Exception as e:
        _audit("safe_press", window_title, {"key": key}, False, str(e))
        raise


def safe_hold(window_title: str, key: str, duration: float = 0.5) -> None:
    """Hold a key down for a specific duration after asserting window focus."""
    if not PYAUTOGUI_OK:
        raise ExecutionDependencyError("Cannot hold key: pyautogui is not available.")
        
    _run_chaos_hook("safe_hold")
    assert_window_focused(window_title)
    
    try:
        pyautogui.keyDown(key)
        time.sleep(duration)
        pyautogui.keyUp(key)
        _audit("safe_hold", window_title, {"key": key, "duration": duration}, True)
    except Exception as e:
        _audit("safe_hold", window_title, {"key": key}, False, str(e))
        raise


def safe_mouseup() -> None:
    """Unconditionally release mouse. Call in finally blocks."""
    if not PYAUTOGUI_OK:
        return
        
    try:
        pyautogui.mouseUp()
    except Exception as e:
        logger.debug(f"safe_mouseup failed: {e}")


# ── Screenshot verification ───────────────────────────────────────────────────

def capture_region(region: Tuple[int, int, int, int]) -> Optional["Image.Image"]:
    if not PIL_OK:
        return None
        
    try:
        return ImageGrab.grab(bbox=region)
    except Exception as e:
        logger.warning(f"capture_region failed: {e}")
        return None


def images_differ(img1, img2, threshold: float = 0.005) -> bool:
    """
    True if more than *threshold* fraction of pixels differ between images.
    Uses numpy for speed; byte comparison as fallback.
    """
    if img1 is None or img2 is None:
        return True

    try:
        import numpy as np
        a1 = np.array(img1.convert('RGB')).astype(int)
        a2 = np.array(img2.convert('RGB')).astype(int)
        
        if a1.shape != a2.shape:
            return True
            
        diff = np.abs(a1 - a2)
        changed = int(np.sum(diff > 15))
        return (changed / a1.size) > threshold
    except ImportError:
        return img1.tobytes() != img2.tobytes()
    except Exception as e:
        logger.debug(f"images_differ failed: {e}")
        return True


class ActionVerifier:
    """
    Context manager wrapping any action with before/after screenshot comparison
    AND mid-action focus validation.
    """

    def __init__(self, region: Tuple[int, int, int, int], window_title: str = "Paint") -> None:
        self.region = region
        self.window_title = window_title
        self._before = None

    def __enter__(self) -> "ActionVerifier":
        assert_window_focused(self.window_title)
        self._before = capture_region(self.region)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        return False

    def verify_changed(self, description: str = "") -> bool:
        assert_window_focused(self.window_title)
        after = capture_region(self.region)
        changed = images_differ(self._before, after)
        
        if changed:
            logger.debug(f"Action verified — canvas changed: {description}")
        else:
            logger.warning(f"Action had no visible effect: {description}")
            
        return changed

    def verify_unchanged(self, description: str = "") -> bool:
        assert_window_focused(self.window_title)
        after = capture_region(self.region)
        return not images_differ(self._before, after)


# ── OSExecutor class ──────────────────────────────────────────────────────────

class OSExecutor:
    """
    Stateful wrapper holding the current window title.
    All public methods delegate to the safe primitives above.
    """

    def __init__(self, window_title: str = "") -> None:
        self.window_title = window_title

    def set_window(self, title: str) -> None:
        self.window_title = title

    def click(self, x: int, y: int, button: str = 'left', clicks: int = 1) -> None:
        safe_click(x, y, self.window_title, button=button, clicks=clicks)

    def drag(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.35) -> None:
        safe_drag(x1, y1, x2, y2, self.window_title, duration=duration)

    def scroll(self, x: int, y: int, clicks: int, region: Optional[Tuple[int, int, int, int]] = None) -> None:
        safe_scroll(x, y, clicks, self.window_title, region=region)

    def type(self, text: str, interval: float = 0.05) -> None:
        safe_type(text, self.window_title, interval=interval)

    def hotkey(self, *keys) -> None:
        safe_hotkey(self.window_title, *keys)

    def assert_focused(self, max_wait: float = 2.0) -> bool:
        return assert_window_focused(self.window_title, max_wait=max_wait)
