"""
core/execution/side_effect_observation.py

Read-only observation of filesystem side effects.

This module never mutates state: it reads the authoritative bytes currently on
disk and reports a digest. It is shared by:

- IntentDispatcher: post-dispatch verification before an intent may reach
  COMPLETED (kernel-side observation, independent of whatever the worker
  reported).
- IntentRecovery: reconciliation of orphaned intents after a crash, where the
  observed digest is compared against the expected digest recorded in the WAL
  BEFORE the effect was attempted.

Callers must compute expected digests independently (from the intended content)
so a shared bug in this module cannot mask a mismatch.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FileObservation:
    """Immutable snapshot of a file's current on-disk state."""

    path: str
    exists: bool
    size: int
    sha256: Optional[str]  # None when the file does not exist

    @property
    def digest(self) -> Optional[str]:
        return self.sha256


def observe_file(path: str) -> FileObservation:
    """
    Read the file at `path` and return its size and sha256.

    A missing file is an observation, not an error: exists=False, sha256=None.
    Other OS errors (permissions, etc.) are raised to the caller — they must
    not be silently converted into a successful-looking observation.
    """
    try:
        with open(path, "rb") as f:
            data = f.read()
    except FileNotFoundError:
        return FileObservation(path=path, exists=False, size=0, sha256=None)
    return FileObservation(
        path=path,
        exists=True,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def sha256_of_bytes(data: bytes) -> str:
    """Digest helper so callers do not re-implement hashing inconsistently."""
    return hashlib.sha256(data).hexdigest()
