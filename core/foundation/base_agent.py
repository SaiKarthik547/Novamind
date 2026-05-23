"""
core/base_agent.py

The foundational base class for all NovaMind agents.
Enforces the strict O(1) branchless execution architecture.
Provides a universal capability registry (plugin model) so agents can 
communicate and execute actions without if/elif dispatch chains.

Phase 7: EffectJournal now tags every side-effect with epoch_id and
logical_clock so the ReplayEngine can reconstruct causal ordering
deterministically without relying on wall-clock timestamps.
"""
import logging
import uuid
import time
import json
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field
from core.runtime.agent_context import AgentContext

# Phase 7 synchronization primitives — imported lazily to avoid circular
# imports during early boot (main.py registers agents before the loop starts).
try:
    from core.sync.synchronization import get_runtime_clock, get_epoch_manager
    _SYNC_AVAILABLE = True
except ImportError:
    _SYNC_AVAILABLE = False

logger = logging.getLogger("BaseAgent")

class EffectJournal:
    """
    Isolates irreversible side-effects (e.g., file writes, OS commands).
    Ensures that during a replay, identical commands don't re-execute but yield the logged outcome.
    """
    def __init__(self):
        self.log: List[Dict[str, Any]] = []

    def record_effect(self, action: str, parameters: dict, result: dict):
        # Tag with Logical Clock and Epoch for causal replay ordering.
        # Falls back gracefully if synchronization module is not yet available
        # (e.g., during unit tests that don't boot the full runtime).
        clock_value = 0
        epoch_id = 0
        if _SYNC_AVAILABLE:
            try:
                clock_value = get_runtime_clock().tick()
                epoch_id = get_epoch_manager().current
            except Exception:
                pass

        self.log.append({
            "id": str(uuid.uuid4()),
            "timestamp": time.time(),
            "action": action,
            "parameters": parameters,
            "result": result,
            "epoch_id": epoch_id,
            "logical_clock": clock_value,
        })

class BaseAgent:
    """
    All agents inherit from BaseAgent.
    Subclasses define their actions in `self.handlers` (a dictionary).
    If an action is missing locally, it falls back to `_GLOBAL_REGISTRY`.
    Zero if/elif/else statements in execution logic.
    """
    
    # Plugin registry — agents can register capabilities at runtime
    _GLOBAL_REGISTRY: Dict[str, Callable] = {}

    def __init__(self, name: str, role: str, context: Optional[AgentContext] = None):
        super().__init__()
        self.name = name
        self.role = role
        self.context = context
        self.handlers: Dict[str, Callable] = {}
        self._action_log: list = []
        self.effect_journal = EffectJournal()

    def get_state(self) -> dict:
        """Mandatory serialization contract for StateSnapshotManager."""
        return {
            "action_log": self._action_log,
            "effect_journal": self.effect_journal.log
        }

    def set_state(self, state: dict):
        """Restores state from a snapshot during recovery boot."""
        self._action_log = state.get("action_log", [])
        self.effect_journal.log = state.get("effect_journal", [])

    @classmethod
    def register_capability(cls, action_name: str, handler: Callable) -> None:
        """
        Register a global capability accessible by any agent.
        O(1) insertion.
        """
        cls._GLOBAL_REGISTRY[action_name] = handler
        logger.info(f"[BaseAgent] Capability registered: {action_name}")

    def execute(self, action_or_context: Any, parameters: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        O(1) dynamic dispatcher.
        Checks local handlers first, then global registry.
        Phase 8: Supports AgentContext injection.
        """
        context = None
        if hasattr(action_or_context, 'action'):
            context = action_or_context
            action = context.action
            parameters = context.parameters
        else:
            action = action_or_context
            parameters = parameters or {}

        handler = self.handlers.get(action, self._GLOBAL_REGISTRY.get(action))
        
        _no_fn = {True: lambda: {"success": False, "error": f"Unknown action: {action}"}}
        res_no_fn = _no_fn.get(handler is None)
        return res_no_fn() if res_no_fn else self._run_fn(handler, action, parameters, context)

    def _run_fn(self, fn: Callable, action: str, parameters: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
        try:
            # If the handler expects a context (e.g. has a _context kwarg), we should provide it.
            # But for simple migration, we just pass parameters and let the handler extract what it needs,
            # or we pass context explicitly if the handler supports it.
            # To be safe in Python, we can check if the function accepts it, or just pass it as _context.
            import inspect
            sig = inspect.signature(fn)
            kwargs = dict(parameters)
            if "_context" in sig.parameters:
                kwargs["_context"] = context
            elif "context" in sig.parameters:
                kwargs["context"] = context

            result = fn(**kwargs)
            self._log(action, parameters, result.get("success", False))
            
            # If the handler explicitly tags side-effects, log them
            if result.get("is_irreversible", False):
                self.effect_journal.record_effect(action, parameters, result)
                
            logger.debug(f"[BaseAgent] {action} -> success={result.get('success')}")
            return result
        except Exception as e:
            logger.error(f"BaseAgent.{action}: {e}")
            self._log(action, parameters, False, str(e))
            return {"success": False, "error": str(e)}

    def _log(self, action: str, parameters: Dict[str, Any], success: bool, error: str = "") -> None:
        """Internal telemetry log for the agent instance."""
        entry = {
            "action": action,
            "params": parameters,
            "success": success,
            "error": error
        }
        self._action_log.append(entry)
        self._action_log[:] = self._action_log[-100:]  # keep last 100
