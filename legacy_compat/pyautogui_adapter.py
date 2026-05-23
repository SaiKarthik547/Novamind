import logging
from typing import Dict, Any
import pyautogui


from core.adapters.adapter_contract import ApplicationAdapter, AdapterState, VerificationMode
from core.telemetry.telemetry_event import ReplayIntegrityLevel

logger = logging.getLogger("PyAutoGUIAdapter")

class PyAutoGUIAdapter(ApplicationAdapter):
    """
    DEPRECATED: Legacy compatibility wrapper for old GUI automation.
    Runs entirely in NON_DETERMINISTIC mode because it seizes the active desktop.
    Will be fully removed once headless execution is complete.
    """
    def __init__(self):
        self._state = AdapterState.CREATED
        
    def get_state(self) -> AdapterState:
        return self._state

    def initialize(self) -> bool:
        self._state = AdapterState.INITIALIZING
        pyautogui.FAILSAFE = True
        return True

    def attach(self) -> bool:
        self._state = AdapterState.ATTACHED
        logger.warning("Attached NON_DETERMINISTIC legacy UI automation adapter.")
        return True

    def execute(self, command: Dict[str, Any]) -> Any:
        self._state = AdapterState.EXECUTING
        action = command.get("action")
        
        # Explicit downgrade of execution lineage determinism
        logger.warning("Execution lineage downgraded: NON_DETERMINISTIC")
        
        try:
            if action == "click":
                x, y = command.get("x", 0), command.get("y", 0)
                pyautogui.click(x, y)
            elif action == "type":
                text = command.get("text", "")
                pyautogui.typewrite(text)
            elif action == "press":
                key = command.get("key", "enter")
                pyautogui.press(key)
        except Exception as e:
            logger.error(f"Legacy UI failure: {e}")
            self._state = AdapterState.DEGRADED
            return {"success": False, "error": str(e), "integrity": ReplayIntegrityLevel.NON_DETERMINISTIC.value}
            
        self._state = AdapterState.ATTACHED
        return {"success": True, "integrity": ReplayIntegrityLevel.NON_DETERMINISTIC.value}

    def verify(self, mode: VerificationMode) -> bool:
        self._state = AdapterState.VERIFYING
        # Visual/Structural verification is impossible with pure PyAutoGUI 
        # unless coupled with Vision pipeline, which is also non-deterministic here.
        self._state = AdapterState.ATTACHED
        return mode == VerificationMode.SEMANTIC # Assume true, but highly unreliable

    def reconcile(self) -> bool:
        self._state = AdapterState.RECONCILING
        # No way to reconcile a failed blind click.
        self._state = AdapterState.ATTACHED
        return False

    def teardown(self) -> None:
        self._state = AdapterState.TERMINATED
