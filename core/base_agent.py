"""
core/base_agent.py

The foundational base class for all NovaMind agents.
Enforces the strict O(1) branchless execution architecture.
Provides a universal capability registry (plugin model) so agents can 
communicate and execute actions without if/elif dispatch chains.
"""
import logging
from typing import Any, Callable, Dict

logger = logging.getLogger("BaseAgent")

class BaseAgent:
    """
    All agents inherit from BaseAgent.
    Subclasses define their actions in `self.handlers` (a dictionary).
    If an action is missing locally, it falls back to `_GLOBAL_REGISTRY`.
    Zero if/elif/else statements in execution logic.
    """
    
    # Plugin registry — agents can register capabilities at runtime
    _GLOBAL_REGISTRY: Dict[str, Callable] = {}

    def __init__(self) -> None:
        self.handlers: Dict[str, Callable] = {}
        self._action_log: list = []

    @classmethod
    def register_capability(cls, action_name: str, handler: Callable) -> None:
        """
        Register a global capability accessible by any agent.
        O(1) insertion.
        """
        cls._GLOBAL_REGISTRY[action_name] = handler
        logger.info(f"[BaseAgent] Capability registered: {action_name}")

    def execute(self, action: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        O(1) dynamic dispatcher.
        Checks local handlers first, then global registry.
        """
        handler = self.handlers.get(action, self._GLOBAL_REGISTRY.get(action))
        
        _no_fn = {True: lambda: {"success": False, "error": f"Unknown action: {action}"}}
        res_no_fn = _no_fn.get(handler is None)
        return res_no_fn() if res_no_fn else self._run_fn(handler, action, parameters)

    def _run_fn(self, fn: Callable, action: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        try:
            result = fn(**parameters)
            self._log(action, parameters, result.get("success", False))
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
