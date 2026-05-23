"""
core/runtime/exceptions.py
Structured violation hierarchy for deterministic supervisor authority.
"""

class CapabilityViolation(Exception):
    """Base exception for all worker boundary/sandbox escapes."""
    pass

class ImportCapabilityViolation(CapabilityViolation):
    """Worker attempted to import a disallowed module outside its capability lease."""
    pass

class ProcessSpawnViolation(CapabilityViolation):
    """Worker attempted to fork a child process, violating the Job Object limits."""
    pass

class NetworkCapabilityViolation(CapabilityViolation):
    """Worker attempted unauthorized network I/O."""
    pass

class FilesystemCapabilityViolation(CapabilityViolation):
    """Worker attempted unauthorized file access."""
    pass

class JobAssignmentError(Exception):
    """Kernel failed to assign the worker to a Job Object (PID race, dead process)."""
    pass
