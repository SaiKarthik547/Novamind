"""
core/legacy/legacy_ui_adapter.py
L1-C: Quarantine zone for ALL pyautogui usage.

This is the ONLY place pyautogui may be called.
All actions here are classified NON_DETERMINISTIC.
They are NOT replayed. They produce observational WAL entries only.

Rules:
- Do NOT import pyautogui anywhere else in the codebase.
- Do NOT add new capabilities here without adding them to CapabilityRegistry first.
- All calls MUST originate from KernelExecutionFacade._route_legacy().
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict

logger = logging.getLogger("LegacyUIAdapter")

# ── Lazy import guard ─────────────────────────────────────────────────────────
try:
    import pyautogui
    pyautogui.FAILSAFE = True   # Move mouse to corner to abort
    pyautogui.PAUSE = 0.05      # 50ms between actions
    _PYAUTOGUI_AVAILABLE = True
except ImportError:
    _PYAUTOGUI_AVAILABLE = False
    logger.warning(
        "[LegacyUIAdapter] pyautogui not installed. "
        "All NON_DETERMINISTIC UI capabilities will return error."
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Adapter
# ─────────────────────────────────────────────────────────────────────────────

class LegacyUIAdapter:
    """
    Quarantined non-deterministic UI automation.

    CRITICAL CLASSIFICATION:
        determinism_class = NON_DETERMINISTIC
        replay_policy     = SKIP
        rollback_policy   = HUMAN_REQUIRED

    Do NOT promote anything from this class to a deterministic adapter.
    """

    SUPPORTED_CAPABILITIES = {
        "ui.mouse_click",
        "ui.keyboard_type",
        "ui.hotkey",
        "ui.screenshot",
    }

    def execute_capability(self, capability: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Entry point from KernelExecutionFacade._route_legacy() ONLY.
        """
        if capability not in self.SUPPORTED_CAPABILITIES:
            return {
                "success": False,
                "error": f"LegacyUIAdapter does not support capability: {capability}",
            }

        if not _PYAUTOGUI_AVAILABLE:
            return {
                "success": False,
                "error": "pyautogui is not installed. Cannot execute UI capability.",
                "capability": capability,
            }

        start = time.monotonic()
        try:
            if capability == "ui.mouse_click":
                result = self._mouse_click(payload)
            elif capability == "ui.keyboard_type":
                result = self._keyboard_type(payload)
            elif capability == "ui.hotkey":
                result = self._hotkey(payload)
            elif capability == "ui.screenshot":
                result = self._screenshot(payload)
            else:
                result = {"success": False, "error": "Unrouted capability"}
        except Exception as exc:
            # NON_DETERMINISTIC failures are logged but NOT re-raised.
            # The kernel must not crash due to UI automation failures.
            logger.error(f"[LegacyUIAdapter] {capability} raised exception: {exc}", exc_info=True)
            result = {"success": False, "error": str(exc)}

        result["duration_ms"] = int((time.monotonic() - start) * 1000)
        result["capability"] = capability
        result["determinism_class"] = "NON_DETERMINISTIC"
        result["replay_policy"] = "SKIP"
        return result

    # ── Capability implementations ────────────────────────────────────────────

    def _mouse_click(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        x = payload.get("x")
        y = payload.get("y")
        button = payload.get("button", "left")
        clicks = payload.get("clicks", 1)

        if x is None or y is None:
            return {"success": False, "error": "mouse_click requires 'x' and 'y' in payload"}

        pyautogui.click(x=x, y=y, button=button, clicks=clicks)
        logger.info(f"[LegacyUIAdapter] mouse_click x={x} y={y} button={button} clicks={clicks}")
        return {"success": True}

    def _keyboard_type(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        text = payload.get("text", "")
        interval = payload.get("interval", 0.02)

        if not text:
            return {"success": False, "error": "keyboard_type requires 'text' in payload"}

        pyautogui.typewrite(text, interval=interval)
        logger.info(f"[LegacyUIAdapter] keyboard_type len={len(text)}")
        return {"success": True}

    def _hotkey(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        keys = payload.get("keys", [])

        if not keys:
            return {"success": False, "error": "hotkey requires 'keys' list in payload"}

        pyautogui.hotkey(*keys)
        logger.info(f"[LegacyUIAdapter] hotkey keys={keys}")
        return {"success": True}

    def _screenshot(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        save_path = payload.get("save_path")
        region = payload.get("region")  # (x, y, w, h) or None for full screen

        screenshot = pyautogui.screenshot(region=region)

        if save_path:
            screenshot.save(save_path)
            logger.info(f"[LegacyUIAdapter] screenshot saved to {save_path}")
            return {"success": True, "saved_to": save_path}

        # Return as base64 if no save_path
        import io, base64
        buf = io.BytesIO()
        screenshot.save(buf, format="PNG")
        encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
        return {"success": True, "image_base64": encoded}
