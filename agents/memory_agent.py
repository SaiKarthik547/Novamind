"""
MemoryAgent — Standalone agent wrapping MemorySystem.

Provides:
  • assemble_context(request)  — pull relevant episodic + semantic memories
  • consolidate()              — prune old memories, compact learning journal
  • search(query, kind, limit) — dict-dispatch search (O(1) kind → method)
  • store_experience(data)     — persist an experience record

Zero if/else routing chains — all dispatch via dict lookup or frozenset.
"""
import logging
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from core.foundation.base_agent import BaseAgent

logger = logging.getLogger("MemoryAgent")


class MemoryAgent(BaseAgent):
    """
    Thin orchestration layer over MemorySystem.

    Usage
    -----
    agent = MemoryAgent(memory_system)
    ctx   = agent.assemble_context("open Chrome and search GitHub")
    agent.store_experience({"task": "...", "success": True, ...})
    agent.consolidate()
    """

    # Maximum number of items returned per context section
    _CONTEXT_LIMITS: Dict[str, int] = {
        "experiences":   5,
        "skills":        3,
        "errors":        3,
        "preferences":   20,
    }

    # Valid search kinds — frozenset O(1) membership test
    _VALID_KINDS: frozenset = frozenset({
        "experiences", "skills", "errors", "preferences", "sessions",
    })

    def __init__(self, memory_system=None, db_path: Optional[str] = None):
        super().__init__(name=self.__class__.__name__, role="Agent")
        # Accept an existing MemorySystem or build a fresh one
        if memory_system is not None:
            self.memory = memory_system
        else:
            from memory.memory_system import MemorySystem
            self.memory = MemorySystem(db_path=db_path)

        # O(1) dict dispatch: search kind → method reference
        self._SEARCH_DISPATCH: Dict[str, Any] = {
            "experiences": self._search_experiences,
            "skills":      self._search_skills,
            "errors":      self._search_errors,
            "preferences": self._search_preferences,
            "sessions":    self._search_sessions,
        }

        self.handlers = {
            "assemble_context": self.assemble_context,
            "consolidate": self.consolidate,
            "search": self.search,
            "store_experience": self.store_experience,
            "remember": self.remember,
            "get_stats": self.get_stats,
        }

        logger.info("MemoryAgent ready — db: %s", self.memory.db_path)

    # ── Public API ─────────────────────────────────────────────────────────────

    def assemble_context(self, request: str) -> Dict[str, Any]:
        """
        Build a rich context dict for the Brain / task planner.
        Pulls similar past experiences, relevant skills, and recent errors.
        """
        ctx: Dict[str, Any] = {"assembled_at": datetime.now().isoformat()}

        _SECTION_FN: Dict[str, Any] = {
            "experiences": lambda: self._safe(
                self.memory.find_similar_experiences,
                request,
                limit=self._CONTEXT_LIMITS["experiences"],
            ),
            "skills": lambda: self._safe(
                self.memory.get_relevant_skills,
                request,
                limit=self._CONTEXT_LIMITS["skills"],
            ),
            "errors": lambda: self._safe(
                self.memory.get_recent_errors,
                limit=self._CONTEXT_LIMITS["errors"],
            ),
            "preferences": lambda: self._safe(
                self.memory.get_all_preferences,
            ),
        }

        # Dict dispatch: populate each section (no if/else per key)
        for section, fn in _SECTION_FN.items():
            result = fn()
            result and ctx.update({section: result})

        return ctx

    def consolidate(self, days_to_keep: int = 30) -> Dict[str, int]:
        """
        Prune old memories + compact the learning journal.
        Returns counts of pruned rows per table.
        """
        cutoff = (datetime.now() - timedelta(days=days_to_keep)).isoformat()

        _PRUNE_FN: Dict[str, Any] = {
            "memories":         lambda: self._safe(
                self.memory.prune_old_memories, cutoff),
            "learning_journal": lambda: self._safe(
                self.memory.compact_learning_journal, cutoff),
            "llm_calls":        lambda: self._safe(
                self.memory.prune_old_llm_calls, cutoff),
        }

        summary: Dict[str, int] = {}
        for table, fn in _PRUNE_FN.items():
            n = fn()
            summary[table] = n or 0

        logger.info("Consolidation complete: %s", summary)
        return summary

    def search(self, query: str, kind: str = "experiences",
               limit: int = 10) -> List[Dict]:
        """
        O(1) dict-dispatch search over MemorySystem.

        Parameters
        ----------
        kind : one of "experiences" | "skills" | "errors" |
                       "preferences" | "sessions"
        """
        # frozenset O(1) guard — unknown kinds return [] with a warning
        kind in self._VALID_KINDS or logger.warning(
            "MemoryAgent.search: unknown kind %r — returning empty", kind)
        fn = self._SEARCH_DISPATCH.get(kind, lambda q, lim: [])
        return fn(query, limit) or []

    def store_experience(self, data: Dict) -> bool:
        """Persist one experience dict to MemorySystem."""
        try:
            self.memory.store_experience(data)
            return True
        except Exception as exc:
            logger.error("store_experience: %s", exc)
            return False

    def remember(self, content: str, kind: str = "episodic",
                 tags: Optional[List[str]] = None,
                 importance: float = 0.5) -> bool:
        """Store a free-form memory entry."""
        try:
            self.memory.add_memory(
                content=content,
                memory_type=kind,
                tags=tags or [],
                importance=importance,
            )
            return True
        except Exception as exc:
            logger.error("remember: %s", exc)
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Return summary statistics from MemorySystem."""
        return self._safe(self.memory.get_memory_stats) or {}

    # ── Internal search helpers (called by _SEARCH_DISPATCH) ──────────────────

    def _search_experiences(self, query: str, limit: int) -> List[Dict]:
        return self._safe(
            self.memory.find_similar_experiences, query, limit=limit) or []

    def _search_skills(self, query: str, limit: int) -> List[Dict]:
        return self._safe(
            self.memory.get_relevant_skills, query, limit=limit) or []

    def _search_errors(self, _query: str, limit: int) -> List[Dict]:
        return self._safe(self.memory.get_recent_errors, limit=limit) or []

    def _search_preferences(self, _query: str, _limit: int) -> List[Dict]:
        prefs = self._safe(self.memory.get_all_preferences) or {}
        return [{"key": k, "value": v} for k, v in prefs.items()]

    def _search_sessions(self, _query: str, limit: int) -> List[Dict]:
        return self._safe(self.memory.get_recent_sessions, limit=limit) or []

    # ── Utility ────────────────────────────────────────────────────────────────

    @staticmethod
    def _safe(fn, *args, **kwargs) -> Any:
        """Call *fn* with suppressed exceptions; returns None on failure."""
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            logger.debug("MemoryAgent._safe(%s): %s", fn.__name__, exc)
            return None
