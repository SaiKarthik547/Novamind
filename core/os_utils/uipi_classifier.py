"""
core/os_utils/uipi_classifier.py

Phase 15A.5: Integrity & UIPI Classification
Validates capability targets against Windows User Interface Privilege Isolation (UIPI) 
and mandatory integrity control mechanisms.

Prevents NovaMind from hallucinating success when attempting to inject messages 
into elevated (High Integrity) applications from a Medium Integrity context.
"""

import ctypes
import logging
from enum import IntEnum

logger = logging.getLogger("IntegrityClassifier")

class IntegrityLevel(IntEnum):
    UNTRUSTED = 0x0000
    LOW = 0x1000
    MEDIUM = 0x2000
    HIGH = 0x3000
    SYSTEM = 0x4000
    PROTECTED = 0x5000

class UIPIViolationError(Exception):
    """Raised when an execution intent attempts to violate UIPI boundaries."""
    pass

class IntegrityClassifier:
    """
    Authoritative classifier for Windows integrity boundaries.
    """
    _instance = None
    _singleton_lock = __import__("threading").Lock()

    @classmethod
    def get_instance(cls) -> 'IntegrityClassifier':
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self._current_integrity = self._get_current_process_integrity()

    @property
    def current_integrity(self) -> IntegrityLevel:
        return self._current_integrity

    def _get_current_process_integrity(self) -> IntegrityLevel:
        """
        Queries the token of the current NovaMind Python process.
        Returns the mapped IntegrityLevel enum.
        """
        try:
            import win32security
            import win32api
            import win32con
            
            token = win32security.OpenProcessToken(
                win32api.GetCurrentProcess(),
                win32con.TOKEN_QUERY
            )
            # TokenIntegrityLevel is info class 25
            sid_and_attributes = win32security.GetTokenInformation(token, 25)
            # The SID structure returns the RID (Relative ID) which corresponds to the Integrity Level
            rid = win32security.GetSidSubAuthority(sid_and_attributes[0], 0)
            
            try:
                return IntegrityLevel(rid)
            except ValueError:
                if rid > IntegrityLevel.SYSTEM:
                    return IntegrityLevel.SYSTEM
                return IntegrityLevel.MEDIUM # Fallback
                
        except ImportError:
            logger.warning("[IntegrityClassifier] win32security not available. Assuming MEDIUM integrity.")
            return IntegrityLevel.MEDIUM
        except Exception as e:
            logger.error(f"[IntegrityClassifier] Failed to query current process token: {e}")
            return IntegrityLevel.MEDIUM

    def get_hwnd_integrity(self, hwnd: int) -> IntegrityLevel:
        """
        Queries the integrity level of the process owning the given HWND.
        """
        try:
            import win32security
            import win32api
            import win32con
            
            user32 = ctypes.windll.user32
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            
            if pid.value == 0:
                raise ValueError(f"Invalid HWND {hwnd}")
                
            process_handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION, False, pid.value)
            token = win32security.OpenProcessToken(process_handle, win32con.TOKEN_QUERY)
            sid_and_attributes = win32security.GetTokenInformation(token, 25)
            rid = win32security.GetSidSubAuthority(sid_and_attributes[0], 0)
            
            win32api.CloseHandle(process_handle)
            
            try:
                return IntegrityLevel(rid)
            except ValueError:
                if rid > IntegrityLevel.SYSTEM:
                    return IntegrityLevel.SYSTEM
                return IntegrityLevel.MEDIUM
                
        except Exception as e:
            logger.error(f"[IntegrityClassifier] Failed to query target HWND {hwnd} token: {e}")
            # If we get Access Denied opening the token, it's highly likely it's a higher integrity process.
            # Default to High in failure cases to be safe against UIPI bounds.
            return IntegrityLevel.HIGH

    def assert_uipi_compatibility(self, target_hwnd: int) -> None:
        """
        Validates that the current process has equal or higher integrity than the target.
        Throws UIPIViolationError if injection is impossible.
        """
        target_integrity = self.get_hwnd_integrity(target_hwnd)
        
        if target_integrity > self._current_integrity:
            raise UIPIViolationError(
                f"UIPI Blocked: Cannot send messages to HWND {target_hwnd}. "
                f"Target requires {target_integrity.name} but NovaMind is running as {self._current_integrity.name}."
            )
            
        logger.debug(f"[IntegrityClassifier] UIPI check passed for HWND {target_hwnd} ({target_integrity.name} <= {self._current_integrity.name})")
