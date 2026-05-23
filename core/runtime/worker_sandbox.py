"""
core/runtime/worker_sandbox.py
Windows Job Objects containment wrapper.
Establishes the OS-level deterministic boundary for worker processes.
"""

import sys
import ctypes
import logging
from ctypes import wintypes
from typing import Optional

from core.runtime.exceptions import JobAssignmentError

logger = logging.getLogger(__name__)

# Only functional on Windows
if sys.platform == "win32":
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    # --- Windows Constants ---
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x0100
    JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x0008
    JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x0400

    JobObjectExtendedLimitInformation = 9
    JobObjectCpuRateControlInformation = 15

    JOB_OBJECT_CPU_RATE_CONTROL_ENABLE = 0x1
    JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP = 0x4

    PROCESS_SET_QUOTA = 0x0100
    PROCESS_TERMINATE = 0x0001

    # --- Structures ---
    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.POINTER(ctypes.c_ulong)), # ULONG_PTR
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class JOBOBJECT_CPU_RATE_CONTROL_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("ControlFlags", wintypes.DWORD),
            ("CpuRate", wintypes.DWORD), # x 10000 (e.g., 20% = 2000)
        ]

    # Function Signatures
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]

    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD
    ]

    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


class WorkerSandbox:
    """
    Wraps a Windows Job Object to enforce OS-level constraints on worker processes.
    If the kernel/supervisor dies, the OS guarantees immediate death of all bound workers.
    """
    def __init__(self, name: str, profile_name: str = "default", max_memory_mb: int = 512, cpu_limit_pct: int = 0):
        self.name = name
        self.profile = profile_name
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self.cpu_limit_pct = cpu_limit_pct
        self._job_handle: Optional[int] = None
        
        if sys.platform != "win32":
            logger.warning(f"WorkerSandbox ({name}) is a no-op on non-Windows platforms.")
            return

        self._create_job_object()
        self._apply_limits()

    def _create_job_object(self):
        job_name = f"NovaMind_WorkerJob_{self.name}"
        self._job_handle = kernel32.CreateJobObjectW(None, job_name)
        if not self._job_handle:
            err = ctypes.get_last_error()
            raise JobAssignmentError(f"Failed to create Job Object. Error code: {err}")

    def _apply_limits(self):
        # 1. Extended Limit Information (Memory, Active Processes, Kill-on-close)
        limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limits.BasicLimitInformation.LimitFlags = (
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE |
            JOB_OBJECT_LIMIT_PROCESS_MEMORY |
            JOB_OBJECT_LIMIT_ACTIVE_PROCESS |
            JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
        )
        limits.BasicLimitInformation.ActiveProcessLimit = 8  # Prevent fork-bombs
        limits.ProcessMemoryLimit = self.max_memory_bytes

        res = kernel32.SetInformationJobObject(
            self._job_handle,
            JobObjectExtendedLimitInformation,
            ctypes.byref(limits),
            ctypes.sizeof(limits)
        )
        if not res:
            err = ctypes.get_last_error()
            raise JobAssignmentError(f"Failed to set extended job limits. Error code: {err}")

        # 2. CPU Rate Control Information (Optional fallback)
        if self.cpu_limit_pct > 0 and self.cpu_limit_pct < 100:
            cpu_limits = JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
            cpu_limits.ControlFlags = JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP
            cpu_limits.CpuRate = self.cpu_limit_pct * 100

            res = kernel32.SetInformationJobObject(
                self._job_handle,
                JobObjectCpuRateControlInformation,
                ctypes.byref(cpu_limits),
                ctypes.sizeof(cpu_limits)
            )
            if not res:
                # Graceful fallback for CPU limiting as per validation instructions
                err = ctypes.get_last_error()
                logger.warning(f"Failed to set CPU limits for Job Object (Error {err}). CPU rate limiting may not be supported on this host. Continuing degraded.")

    def assign_process(self, pid: int):
        """
        Assigns a process to the Job Object via process handle.
        MUST be called immediately after spawn to minimize rogue window.
        """
        if sys.platform != "win32":
            return

        if not self._job_handle:
            raise JobAssignmentError("Job object not initialized.")

        # Obtain process handle safely (PROCESS_SET_QUOTA | PROCESS_TERMINATE)
        h_process = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        if not h_process:
            err = ctypes.get_last_error()
            raise JobAssignmentError(f"Failed to open process handle for PID {pid}. Error code: {err}")

        try:
            res = kernel32.AssignProcessToJobObject(self._job_handle, h_process)
            if not res:
                err = ctypes.get_last_error()
                raise JobAssignmentError(f"Failed to assign handle to Job Object. Error code: {err}")
        finally:
            kernel32.CloseHandle(h_process)

    def close(self):
        """Closes the Job handle, terminating all contained processes immediately."""
        if sys.platform == "win32" and self._job_handle:
            kernel32.CloseHandle(self._job_handle)
            self._job_handle = None

    def __del__(self):
        self.close()
