"""
core/execution/window_lifecycle.py

Phase 15A.5: Window Lifecycle Governance
Tracks HWND validity, destruction detection, recreation tracking, 
thread affinity metadata, and process ownership.

This is a mandatory foundational layer before concurrent UI orchestration.
"""

import ctypes
import logging
import threading
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger("WindowLifecycleTracker")

# Win32 API Definitions
_user32 = ctypes.windll.user32

@dataclass(frozen=True)
class WindowAffinity:
    hwnd: int
    thread_id: int
    process_id: int
    
class StaleHandleError(Exception):
    """Raised when an execution lane attempts to dispatch to a dead or reused HWND."""
    pass

class WindowLifecycleTracker:
    """
    Authoritative tracker for HWND validity.
    Prevents the ExecutionScheduler and UIA lanes from dispatching
    ghost commands into stale memory or recreated window handles.
    """
    _instance = None
    _singleton_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> 'WindowLifecycleTracker':
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self._lock = threading.RLock()
        self._tracked_windows: Dict[int, WindowAffinity] = {}

    def track_window(self, hwnd: int) -> Optional[WindowAffinity]:
        """
        Registers a window for lifecycle tracking.
        Extracts its Thread ID and Process ID for affinity mapping.
        Returns None if the HWND is invalid.
        """
        if not self.is_window_valid(hwnd):
            return None
            
        pid = ctypes.c_ulong()
        tid = _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        
        if tid == 0:
            return None
            
        affinity = WindowAffinity(
            hwnd=hwnd,
            thread_id=tid,
            process_id=pid.value
        )
        
        with self._lock:
            self._tracked_windows[hwnd] = affinity
            
        return affinity

    def is_window_valid(self, hwnd: int) -> bool:
        """
        Queries the OS to verify if the HWND is currently valid.
        """
        return _user32.IsWindow(hwnd) != 0

    def assert_valid_and_owned(self, hwnd: int, expected_pid: Optional[int] = None) -> WindowAffinity:
        """
        Validates that the HWND is still alive AND still belongs to the expected process.
        This prevents race conditions where an HWND is destroyed and the integer is reused
        by a completely different process before execution occurs.
        
        Raises StaleHandleError if validation fails.
        """
        if not self.is_window_valid(hwnd):
            with self._lock:
                self._tracked_windows.pop(hwnd, None)
            raise StaleHandleError(f"HWND {hwnd} has been destroyed.")

        with self._lock:
            affinity = self._tracked_windows.get(hwnd)

        # If not tracked yet, track it now
        if not affinity:
            affinity = self.track_window(hwnd)
            if not affinity:
                raise StaleHandleError(f"HWND {hwnd} could not be tracked (dead or inaccessible).")

        if expected_pid is not None and affinity.process_id != expected_pid:
            raise StaleHandleError(
                f"HWND {hwnd} ownership mismatch! "
                f"Expected PID {expected_pid}, found PID {affinity.process_id}. "
                f"Handle reuse detected."
            )

        return affinity

    def untrack_window(self, hwnd: int) -> None:
        """
        Stop tracking a window (e.g., when a cancellation propagates).
        """
        with self._lock:
            self._tracked_windows.pop(hwnd, None)
