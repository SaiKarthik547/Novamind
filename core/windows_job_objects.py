import ctypes
from ctypes import wintypes
import logging
import sys

logger = logging.getLogger("WindowsJobObjects")

# Basic definitions for Windows API
if sys.platform == "win32":
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", ctypes.c_byte * 48), # Padded for brevity, properly it's JOBOBJECT_BASIC_LIMIT_INFORMATION
            ("IoInfo", ctypes.c_byte * 48),                # IO_COUNTERS
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    # Constants
    JobObjectExtendedLimitInformation = 9
    JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
    JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

class WindowsJobObject:
    """
    OS-level process containment using Windows Job Objects.
    Automatically terminates child process trees when the supervisor closes the handle.
    """
    def __init__(self, name: str = None):
        self.handle = None
        if sys.platform != "win32":
            logger.warning("WindowsJobObject is only supported on Windows. Running uncontained.")
            return

        self.handle = kernel32.CreateJobObjectW(None, name)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

        # By default, kill all processes in the job when the handle is closed.
        self._set_kill_on_close()

    def _set_kill_on_close(self):
        if not self.handle: return
        
        limit_info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        # offset 16 is LimitFlags in BasicLimitInformation on 64-bit
        # A proper ctypes mapping is tedious here, but we can do it via a more precise structure if needed.
        # For this prototype, we'll implement a clean structure later. Let's do a basic mapping for LimitFlags.
        class _BASIC(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32),
            ]
        class _EXT(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BASIC),
                ("IoInfo", ctypes.c_byte * 48),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]
            
        info = _EXT()
        # 0x00002000 is JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        info.BasicLimitInformation.LimitFlags = 0x00002000
        
        res = kernel32.SetInformationJobObject(
            self.handle,
            9, # JobObjectExtendedLimitInformation
            ctypes.byref(info),
            ctypes.sizeof(info)
        )
        if not res:
            logger.error("Failed to set KillOnClose on Job Object")

    def assign_process(self, pid: int):
        if not self.handle: return
        
        PROCESS_SET_QUOTA = 0x0100
        PROCESS_TERMINATE = 0x0001
        
        hProcess = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        if not hProcess:
            logger.error(f"Failed to open process {pid} for Job assignment")
            return
            
        res = kernel32.AssignProcessToJobObject(self.handle, hProcess)
        if not res:
            logger.error(f"Failed to assign process {pid} to Job Object: {ctypes.get_last_error()}")
            
        kernel32.CloseHandle(hProcess)

    def close(self):
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None

    def __del__(self):
        self.close()
