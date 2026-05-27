"""
core/os_utils/os_executor.py

Step 4: Multi-Lane Adapter Runtime (Selective HID Fallback Lane)

WARNING: This module has been DEMOTED.
It no longer holds primary OS execution authority.
Win32 Messaging and UIAutomation (COM) are the deterministic primary lanes.
This lane provides Selective HID Fallback (via PyAutoGUI) ONLY as a last resort
for legacy, non-standard, or canvas-based applications (e.g. MS Paint canvas).
"""

import time
import logging
from typing import Optional, Tuple

from core.execution.window_lifecycle import WindowLifecycleTracker, StaleHandleError

logger = logging.getLogger("SelectiveHIDFallbackLane")

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


class HIDFallbackError(Exception):
    """Raised when the fallback lane cannot safely execute."""
    pass


class SelectiveHIDFallbackLane:
    """
    Lane 3: Selective HID Fallback.
    Used ONLY when UIA and Win32 messaging are unavailable.
    Highly fragile. Requires physical mouse/keyboard stealing and focus assertions.
    """

    def __init__(self):
        self._lifecycle_tracker = WindowLifecycleTracker.get_instance()

    def _assert_focus_and_validity(self, hwnd: int, max_wait: float = 2.0) -> bool:
        """
        Validates HWND lifecycle first, then attempts physical focus.
        """
        try:
            self._lifecycle_tracker.assert_valid_and_owned(hwnd)
        except StaleHandleError as e:
            logger.error(f"[HIDFallbackLane] Aborted: {e}")
            raise HIDFallbackError(str(e))

        if not PYGETWINDOW_OK:
            raise HIDFallbackError("pygetwindow unavailable. Cannot assert physical focus.")

        deadline = time.time() + max_wait
        while time.time() < deadline:
            try:
                # Find window by HWND logic would go here.
                # Since pygetwindow mostly uses titles, we do a raw lookup:
                active = gw.getActiveWindow()
                if active and getattr(active, '_hWnd', None) == hwnd:
                    return True
                    
                # Try to force activate
                wins = [w for w in gw.getAllWindows() if getattr(w, '_hWnd', None) == hwnd]
                if wins:
                    wins[0].activate()
                    time.sleep(0.15)
                    return True
            except Exception as e:
                logger.debug(f"[HIDFallbackLane] Focus check failed: {e}")
            time.sleep(0.1)
            
        raise HIDFallbackError(f"Could not establish physical focus on HWND {hwnd} for HID injection.")

    def _release_modifiers(self) -> None:
        if not PYAUTOGUI_OK:
            return
        for key in ('ctrl', 'shift', 'alt', 'win'):
            try:
                pyautogui.keyUp(key)
            except Exception:
                pass

    def physical_click(self, hwnd: int, x: int, y: int, button: str = 'left', clicks: int = 1) -> None:
        """
        Executes a physical mouse click, stealing cursor focus.
        """
        if not PYAUTOGUI_OK:
            raise HIDFallbackError("pyautogui is unavailable.")
            
        self._assert_focus_and_validity(hwnd)
        self._release_modifiers()
        
        try:
            pyautogui.click(x, y, button=button, clicks=clicks, interval=0.1)
            logger.debug(f"[HIDFallbackLane] physical_click on {hwnd} at ({x}, {y})")
        except Exception as e:
            logger.error(f"[HIDFallbackLane] physical_click failed: {e}")
            raise HIDFallbackError(str(e))

    def physical_type(self, hwnd: int, text: str, interval: float = 0.05) -> None:
        """
        Executes physical keystrokes, stealing keyboard focus.
        """
        if not PYAUTOGUI_OK:
            raise HIDFallbackError("pyautogui is unavailable.")
            
        self._assert_focus_and_validity(hwnd)
        self._release_modifiers()
        
        try:
            pyautogui.typewrite(text, interval=interval)
            logger.debug(f"[HIDFallbackLane] physical_type on {hwnd} (len {len(text)})")
        except Exception as e:
            logger.error(f"[HIDFallbackLane] physical_type failed: {e}")
            raise HIDFallbackError(str(e))
