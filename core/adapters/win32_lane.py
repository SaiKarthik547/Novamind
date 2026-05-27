"""
core/adapters/win32_lane.py

Step 4: Multi-Lane Adapter Runtime (Win32 Messaging Lane)
Authoritative execution lane for classical Win32 HWND messaging.
Replaces fragile pyautogui interactions with deterministic OS-level signals.
"""

import ctypes
import ctypes.wintypes as wintypes
import logging
from typing import Dict, Any, Optional

from core.execution.window_lifecycle import WindowLifecycleTracker, StaleHandleError

logger = logging.getLogger("Win32Lane")

# Win32 Constants
SMTO_ABORTIFHUNG = 0x0002
SMTO_NORMAL = 0x0000

class Win32MessagingLane:
    """
    Authoritative Execution Lane for Win32 Messages.
    Guaranteed to strictly check Window Lifecycle before dispatch.
    NEVER uses blocking SendMessage(). Exclusively uses SendMessageTimeout to prevent kernel deadlocks.
    """
    
    def __init__(self):
        self._user32 = ctypes.windll.user32
        self._lifecycle_tracker = WindowLifecycleTracker.get_instance()

    def dispatch_message(self, hwnd: int, msg: int, wparam: int, lparam: int, timeout_ms: int = 5000) -> Optional[int]:
        """
        Safely dispatches a synchronous message to an HWND.
        Returns the LRESULT on success, or None on failure/timeout.
        """
        try:
            # 1. Lifecycle Governance Check
            self._lifecycle_tracker.assert_valid_and_owned(hwnd)
        except StaleHandleError as e:
            logger.error(f"[Win32Lane] Aborted dispatch: {e}")
            return None

        # 2. Execution Dispatch
        result = wintypes.DWORD()
        # SendMessageTimeoutW signature:
        # LRESULT SendMessageTimeoutW(HWND hWnd, UINT Msg, WPARAM wParam, LPARAM lParam, UINT fuFlags, UINT uTimeout, PDWORD_PTR lpdwResult);
        status = self._user32.SendMessageTimeoutW(
            hwnd, 
            msg, 
            wparam, 
            lparam, 
            SMTO_ABORTIFHUNG, 
            timeout_ms, 
            ctypes.byref(result)
        )
        
        if status == 0:
            logger.warning(f"[Win32Lane] SendMessageTimeout failed or timed out for HWND {hwnd}")
            return None
            
        return result.value

    def post_message(self, hwnd: int, msg: int, wparam: int, lparam: int) -> bool:
        """
        Safely posts an asynchronous message to an HWND message queue.
        Returns True if successfully queued.
        """
        try:
            # 1. Lifecycle Governance Check
            self._lifecycle_tracker.assert_valid_and_owned(hwnd)
        except StaleHandleError as e:
            logger.error(f"[Win32Lane] Aborted post: {e}")
            return False
            
        # 2. Execution Dispatch
        status = self._user32.PostMessageW(hwnd, msg, wparam, lparam)
        return status != 0

    def get_window_text(self, hwnd: int) -> Optional[str]:
        """
        Helper for Observational semantics and Verification routines.
        """
        try:
            self._lifecycle_tracker.assert_valid_and_owned(hwnd)
        except StaleHandleError:
            return None
            
        length = self._user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return ""
            
        buffer = ctypes.create_unicode_buffer(length + 1)
        self._user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value
