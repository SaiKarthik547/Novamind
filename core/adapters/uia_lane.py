"""
core/adapters/uia_lane.py

Step 4: Multi-Lane Adapter Runtime (UIAutomation Lane)
Authoritative execution lane for UIAutomation accessibility APIs.
Strictly bound to the COMApartmentExecutor to guarantee STA (Single-Threaded Apartment) compliance.
"""

import logging
from typing import Dict, Any, Optional

from core.execution.com_governance import COMApartmentExecutor
from core.execution.window_lifecycle import WindowLifecycleTracker, StaleHandleError

logger = logging.getLogger("UIAutomationLane")

class UIAutomationLane:
    """
    Authoritative Execution Lane for UIAutomation.
    All COM method calls are dispatched via the centralized STA worker thread.
    """
    
    def __init__(self):
        self._com_executor = COMApartmentExecutor.get_instance()
        self._lifecycle_tracker = WindowLifecycleTracker.get_instance()
        
    def _invoke_element_internal(self, hwnd: int) -> bool:
        """
        Internal implementation executed explicitly on the STA thread.
        Uses comtypes to get the UIA Element from the HWND and invoke its default action.
        """
        try:
            import comtypes.client
            # This requires UIAutomationCore.dll typelib to be generated/available.
            # Fallback wrapper approach for this foundational implementation.
            from comtypes.gen.UIAutomationClient import IUIAutomation, CUIAutomation, UIA_InvokePatternId
            
            uia = comtypes.client.CreateObject(CUIAutomation, interface=IUIAutomation)
            
            # Note: comtypes pointers wrap the raw pointer, so passing the raw HWND integer requires cast
            element = uia.ElementFromHandle(hwnd)
            if not element:
                logger.error(f"[UIAutomationLane] Could not resolve UIA Element from HWND {hwnd}")
                return False
                
            invoke_pattern = element.GetCurrentPattern(UIA_InvokePatternId)
            if not invoke_pattern:
                logger.error(f"[UIAutomationLane] Element {hwnd} does not support InvokePattern")
                return False
                
            # Cast to the actual interface
            invoke_interface = invoke_pattern.QueryInterface(comtypes.gen.UIAutomationClient.IUIAutomationInvokePattern)
            invoke_interface.Invoke()
            return True
            
        except ImportError:
            logger.error("[UIAutomationLane] comtypes not installed or UIAutomationClient typelib not generated.")
            return False
        except Exception as e:
            logger.error(f"[UIAutomationLane] COM Execution failed for HWND {hwnd}: {e}")
            return False

    def invoke_element(self, hwnd: int, timeout_ms: int = 5000) -> bool:
        """
        Public entry point. 
        Validates HWND lifecycle, then routes the heavy COM lifting to the STA thread.
        """
        try:
            # 1. Lifecycle Governance Check
            self._lifecycle_tracker.assert_valid_and_owned(hwnd)
        except StaleHandleError as e:
            logger.error(f"[UIAutomationLane] Aborted UIA invoke: {e}")
            return False
            
        # 2. Safe STA Dispatch
        try:
            result = self._com_executor.execute_in_apartment(
                self._invoke_element_internal, 
                hwnd, 
                timeout=timeout_ms / 1000.0
            )
            return result
        except TimeoutError:
            logger.error(f"[UIAutomationLane] UIA invoke timed out for HWND {hwnd}")
            return False
        except Exception as e:
            logger.error(f"[UIAutomationLane] Unhandled STA failure: {e}")
            return False
