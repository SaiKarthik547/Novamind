"""
core/uia_executor.py

Windows UI Automation (UIA) wrapper via comtypes.
Semantic element finding by name, automation ID, and control type.

This module uses strict state propagation. If UIA is unavailable or
an element is missing, it raises explicit exceptions rather than 
failing silently. This forces upper perception layers to explicitly 
handle fallbacks (like OCR).
"""

import logging
import time
from typing import List, Optional, Tuple

logger = logging.getLogger("UIAExecutor")

class UIAError(Exception):
    """Base exception for UIA errors."""
    pass

class UIAUnavailableError(UIAError):
    """Raised when comtypes/UIA is not initialized."""
    pass

class ElementNotFoundError(UIAError):
    """Raised when an element cannot be found."""
    pass

class WindowNotFoundError(UIAError):
    """Raised when a requested window cannot be found."""
    pass

class ActionFailedError(UIAError):
    """Raised when clicking or setting value fails."""
    pass

# ── UIA bootstrap ─────────────────────────────────────────────────────────────

_uia        = None
_UIA_T      = None
_UIA_OK     = False

try:
    import comtypes.client
    import comtypes.gen

    if not hasattr(comtypes.gen, 'UIAutomationClient'):
        try:
            comtypes.client.GetModule('UIAutomationCore.dll')
        except Exception:
            comtypes.client.GetModule(
                ('{ff48dba4-60ef-4201-aa87-54103eef594e}', 1, 0)
            )

    import comtypes.gen.UIAutomationClient as _UIA_T

    _uia = comtypes.client.CreateObject(
        '{ff48dba4-60ef-4201-aa87-54103eef594e}',
        interface=_UIA_T.IUIAutomation
    )
    _UIA_OK = True
    logger.info("Windows UI Automation initialised via comtypes")
except Exception as _uia_err:
    _UIA_OK = False
    _uia = None
    logger.warning(
        f"UIAExecutor: UIA not available ({_uia_err}) "
        f"— upper layers must use OCR/coordinate fallbacks."
    )


# ── Condition builder ─────────────────────────────────────────────────────────

def _get_prop_ids():
    if not _UIA_OK:
        raise UIAUnavailableError("UIA is not available.")
    return {
        "name":          _UIA_T.UIA_NamePropertyId,
        "automation_id": _UIA_T.UIA_AutomationIdPropertyId,
        "control_type":  _UIA_T.UIA_ControlTypePropertyId,
    }


def _build_condition(name=None, automation_id=None, control_type=None):
    """Build a combined UIA condition from provided filters."""
    if not _UIA_OK:
        raise UIAUnavailableError("Cannot build condition: UIA not available.")
    
    parts = {
        "name":          name,
        "automation_id": automation_id,
        "control_type":  control_type,
    }
    
    prop_ids = _get_prop_ids()
    conditions = []
    
    for key, val in parts.items():
        if val is not None:
            cond = _uia.CreatePropertyCondition(prop_ids[key], val)
            conditions.append(cond)
            
    if not conditions:
        return _uia.CreateTrueCondition()
        
    if len(conditions) == 1:
        return conditions[0]
        
    combined = conditions[0]
    for cond in conditions[1:]:
        combined = _uia.CreateAndCondition(combined, cond)
    return combined


# ── Internal helpers ──────────────────────────────────────────────────────────

def _find_in_element(raw_el, name=None, automation_id=None,
                     control_type=None) -> "UIElement":
    if not _UIA_OK or raw_el is None:
        raise UIAUnavailableError("UIA not available or root element is None.")
        
    cond = _build_condition(name, automation_id, control_type)
    found = raw_el.FindFirst(_UIA_T.TreeScope_Descendants, cond)
    
    if not found:
        raise ElementNotFoundError(f"Could not find element: name={name}, id={automation_id}")
        
    return UIElement(found)


def _find_all_in_element(raw_el, name=None, automation_id=None,
                          control_type=None) -> List["UIElement"]:
    if not _UIA_OK or raw_el is None:
        raise UIAUnavailableError("UIA not available or root element is None.")
        
    cond = _build_condition(name, automation_id, control_type)
    found_arr = raw_el.FindAll(_UIA_T.TreeScope_Descendants, cond)
    
    elements = []
    for i in range(found_arr.Length):
        elements.append(UIElement(found_arr.GetElement(i)))
    return elements


# ── UIElement wrapper ─────────────────────────────────────────────────────────

class UIElement:
    """Thin wrapper around a comtypes IUIAutomationElement."""

    def __init__(self, raw_element) -> None:
        self._el = raw_element

    @property
    def name(self) -> str:
        try:
            return self._el.CurrentName or ""
        except Exception:
            return ""

    @property
    def automation_id(self) -> str:
        try:
            return self._el.CurrentAutomationId or ""
        except Exception:
            return ""

    @property
    def control_type(self) -> int:
        try:
            return self._el.CurrentControlType
        except Exception:
            return -1

    @property
    def bounding_rect(self):
        try:
            return self._el.CurrentBoundingRectangle
        except Exception:
            return None

    @property
    def center(self) -> Optional[Tuple[int, int]]:
        try:
            r = self._el.CurrentBoundingRectangle
            return (r.left + (r.right - r.left) // 2,
                    r.top + (r.bottom - r.top) // 2)
        except Exception:
            return None

    @property
    def is_enabled(self) -> bool:
        try:
            return bool(self._el.CurrentIsEnabled)
        except Exception:
            return False

    def _invoke_pattern(self):
        try:
            return self._el.GetCurrentPattern(_UIA_T.UIA_InvokePatternId)
        except Exception:
            return None

    def _value_pattern(self):
        try:
            return self._el.GetCurrentPattern(_UIA_T.UIA_ValuePatternId)
        except Exception:
            return None

    def _click_centre(self) -> None:
        centre = self.center
        if centre is None:
            raise ActionFailedError("Cannot click: Element has no valid bounding rectangle.")
        try:
            import pyautogui
            pyautogui.click(*centre)
        except Exception as e:
            raise ActionFailedError(f"Fallback click via PyAutoGUI failed: {e}")

    def click(self) -> None:
        """Invoke via UIA InvokePattern, or click centre as fallback."""
        if not _UIA_OK:
            self._click_centre()
            return
            
        pattern = self._invoke_pattern()
        if pattern is not None:
            try:
                invoke = pattern.QueryInterface(_UIA_T.IUIAutomationInvokePattern)
                invoke.Invoke()
                return
            except Exception as e:
                logger.debug(f"Invoke pattern failed: {e}. Falling back to coordinate click.")
        
        self._click_centre()

    def set_value(self, value: str) -> None:
        """Set value via ValuePattern; fall back to triple-click + typewrite."""
        if not _UIA_OK:
            self._set_value_fallback(value)
            return
            
        pattern = self._value_pattern()
        if pattern is not None:
            try:
                val_pat = pattern.QueryInterface(_UIA_T.IUIAutomationValuePattern)
                val_pat.SetValue(value)
                return
            except Exception as e:
                logger.debug(f"Value pattern failed: {e}. Falling back to typing.")
                
        self._set_value_fallback(value)

    def _set_value_fallback(self, value: str) -> None:
        centre = self.center
        if centre is None:
            raise ActionFailedError("Cannot set value: Element has no valid bounding rectangle for triple-click.")
        try:
            import pyautogui
            pyautogui.tripleClick(*centre)
            pyautogui.typewrite(value, interval=0.04)
        except Exception as e:
            raise ActionFailedError(f"Fallback typing via PyAutoGUI failed: {e}")

    def get_value(self) -> str:
        if not _UIA_OK:
            return ""
        pattern = self._value_pattern()
        if pattern is not None:
            try:
                val_pat = pattern.QueryInterface(_UIA_T.IUIAutomationValuePattern)
                return val_pat.CurrentValue or ""
            except Exception:
                pass
        return ""

    def focus(self) -> None:
        try:
            self._el.SetFocus()
        except Exception as e:
            raise ActionFailedError(f"Failed to focus element: {e}")

    def __repr__(self) -> str:
        return f"<UIElement name={self.name!r} id={self.automation_id!r}>"


# ── UIWindow ──────────────────────────────────────────────────────────────────

class UIWindow:
    """Top-level window wrapper returned by UIAExecutor.find_window()."""

    def __init__(self, element: UIElement) -> None:
        self._el = element._el
        self.element = element

    @property
    def title(self) -> str:
        return self.element.name

    def find_element(self, name=None, automation_id=None,
                     control_type=None) -> UIElement:
        return _find_in_element(
            self._el, name=name,
            automation_id=automation_id,
            control_type=control_type,
        )

    def find_all_elements(self, name=None, automation_id=None,
                           control_type=None) -> List[UIElement]:
        return _find_all_in_element(
            self._el, name=name,
            automation_id=automation_id,
            control_type=control_type,
        )


# ── UIAExecutor ───────────────────────────────────────────────────────────────

class UIAExecutor:
    """High-level UIA entry point. All methods raise explicit exceptions on failure."""

    @property
    def available(self) -> bool:
        return _UIA_OK

    def find_window(self, title_contains: str,
                    timeout: float = 5.0) -> UIWindow:
        """Poll for a top-level window whose title contains *title_contains*."""
        if not _UIA_OK:
            raise UIAUnavailableError("Cannot find window: UIA is not available.")
            
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                desktop = _uia.GetRootElement()
                children = desktop.FindAll(
                    _UIA_T.TreeScope_Children,
                    _uia.CreateTrueCondition(),
                )
                for i in range(children.Length):
                    el = children.GetElement(i)
                    try:
                        el_name = el.CurrentName or ""
                        if title_contains.lower() in el_name.lower():
                            return UIWindow(UIElement(el))
                    except Exception:
                        continue
            except Exception as e:
                logger.debug(f"find_window iteration error: {e}")
            time.sleep(0.2)
            
        raise WindowNotFoundError(f"Window containing '{title_contains}' not found after {timeout}s.")

    def find_element(self, window: UIWindow, name=None,
                     automation_id=None, control_type=None) -> UIElement:
        if not _UIA_OK:
            raise UIAUnavailableError("UIA is not available.")
        if window is None:
            raise ValueError("Window cannot be None when searching for an element.")
            
        return _find_in_element(
            window._el, name=name,
            automation_id=automation_id,
            control_type=control_type,
        )

    def find_all_elements(self, window: UIWindow, name=None,
                           automation_id=None, control_type=None) -> List[UIElement]:
        if not _UIA_OK:
            raise UIAUnavailableError("UIA is not available.")
        if window is None:
            raise ValueError("Window cannot be None when searching for elements.")
            
        return _find_all_in_element(
            window._el, name=name,
            automation_id=automation_id,
            control_type=control_type,
        )

    def get_focused_element(self) -> UIElement:
        if not _UIA_OK:
            raise UIAUnavailableError("UIA is not available.")
        try:
            el = _uia.GetFocusedElement()
            if el:
                return UIElement(el)
            raise ElementNotFoundError("No element is currently focused.")
        except Exception as e:
            raise ElementNotFoundError(f"Failed to get focused element: {e}")

    def set_paint_rgb(self, r: int, g: int, b: int) -> None:
        """
        Open Edit Colors in MS Paint and fill RGB fields.
        Automation IDs: 703=Red, 704=Green, 705=Blue (Paint 10/11).
        """
        paint_win = self.find_window("Paint", timeout=3.0)
        
        edit_btn = self.find_element(paint_win, name="Edit colors")
        edit_btn.click()

        time.sleep(0.6)
        dialog = self.find_window("Edit Colors", timeout=3.0)

        rgb_fields = {"703": r, "704": g, "705": b}
        for aid, val in rgb_fields.items():
            field = self.find_element(dialog, automation_id=aid)
            field.set_value(str(int(val)))
            
        ok_btn = self.find_element(dialog, name="OK")
        ok_btn.click()
        time.sleep(0.3)
