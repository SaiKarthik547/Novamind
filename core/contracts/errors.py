"""core/contracts/errors.py

Canonical error taxonomy for the NovaMind runtime.

This module is the authoritative error model for the converged runtime.
Do not create ad-hoc error strings in the execution path; use these classes
or subclass them where the domain genuinely differs.
"""

from __future__ import annotations

from typing import Optional


class RuntimeError(Exception):
    """Base runtime error for the NovaMind kernel path."""
    pass


class AuthorityError(RuntimeError):
    """Raised when an authority boundary is violated."""
    pass


class CapabilityError(RuntimeError):
    """Raised when a capability is missing, invalid, or unauthorized."""
    pass


class IntentValidationError(RuntimeError, ValueError):
    """Raised when an execution intent fails structural/policy validation."""
    pass


class GovernanceError(RuntimeError):
    """Raised when intent governance rejects admission."""
    pass


class SchedulingError(RuntimeError):
    """Raised when the canonical scheduler cannot admit/dispatch."""
    pass


class VerificationError(RuntimeError):
    """Raised when verification semantics fail or are impossible."""
    pass


class RecoveryError(RuntimeError):
    """Raised when WAL/recovery/reconciliation cannot proceed deterministically."""
    pass


class WorkerError(RuntimeError):
    """Raised when worker isolation/supervision fails."""
    pass


class AdapterError(RuntimeError):
    """Raised when a canonical adapter lane fails."""
    pass


class IpError(RuntimeError):
    """Raised when canonical IPC protocol semantics fail."""
    pass


def format_for_serialization(exc: BaseException) -> dict:
    """Minimal, policy-aware serialization helper for error metadata."""
    return {
        "error_type": type(exc).__name__,
        "message": str(exc) or "(no message)",
    }
