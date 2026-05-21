"""
Runtime path helpers for NovaMind.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_FALLBACK_ROOT = _PROJECT_ROOT / ".novamind"


def _probe_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".write_probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink(missing_ok=True)
    return path


@lru_cache(maxsize=1)
def get_runtime_root() -> Path:
    env_roots = [
        Path(raw).expanduser()
        for raw in filter(None, [os.environ.get("NOVAMIND_HOME", "").strip()])
    ]
    candidates = env_roots + [Path.home() / ".novamind", _FALLBACK_ROOT]
    for candidate in candidates:
        try:
            return _probe_dir(candidate)
        except OSError:
            continue
    return _probe_dir(_FALLBACK_ROOT)


def ensure_runtime_dir(*parts: str) -> Path:
    path = get_runtime_root().joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def runtime_path(*parts: str) -> Path:
    path = get_runtime_root().joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
