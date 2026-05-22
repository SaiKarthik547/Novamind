"""
tests/test_focus_chaos.py

Chaos-testing harness for focus-loss safety in the OS execution pipeline.

Strategy:
  - Register a chaos hook that switches focus mid-action.
  - Call a safe primitive (safe_hotkey, safe_click, etc.)
  - Verify that FocusLostError is raised and NO keystrokes were sent.
  - Verify the audit log captured the failure.

Zero if/elif/else — all dispatch is dict-based.
Run with: py -m pytest tests/test_focus_chaos.py -v
"""

import sys
import unittest
from unittest.mock import patch, MagicMock, call

# ── Inject mock modules so tests run without pyautogui installed ─────────────
_mock_pyautogui = MagicMock()
_mock_pygetwindow = MagicMock()
sys.modules.setdefault("pyautogui", _mock_pyautogui)
sys.modules.setdefault("pygetwindow", _mock_pygetwindow)
sys.modules.setdefault("PIL", MagicMock())
sys.modules.setdefault("PIL.Image", MagicMock())
sys.modules.setdefault("PIL.ImageGrab", MagicMock())

from core.os_utils.os_executor import (  # noqa: E402
    _CHAOS_HOOKS, FocusLostError, safe_hotkey, safe_click,
    safe_type, safe_type_clipboard, safe_hotkey,
    get_audit_log, assert_window_focused,
)


class TestFocusGuardBaseline(unittest.TestCase):
    """Verify assert_window_focused raises FocusLostError when focus cannot be established."""

    def setUp(self):
        _CHAOS_HOOKS.clear()

    def test_focus_lost_raises_on_timeout(self):
        """If getActiveWindow always returns wrong title, FocusLostError must be raised."""
        mock_win = MagicMock()
        mock_win.title = "Some Other App"

        _mock_pygetwindow.getActiveWindow.return_value = mock_win
        _mock_pygetwindow.getWindowsWithTitle.return_value = []

        with self.assertRaises(FocusLostError):
            assert_window_focused("Paint", max_wait=0.1)

    def test_focus_succeeds_when_window_active(self):
        """Should return True immediately when the correct window is already active."""
        mock_win = MagicMock()
        mock_win.title = "Untitled - Paint"

        _mock_pygetwindow.getActiveWindow.return_value = mock_win

        result = assert_window_focused("Paint", max_wait=1.0)
        self.assertTrue(result)


class TestChaosHookFocusLoss(unittest.TestCase):
    """Inject a chaos hook that triggers focus loss before an action and verify abort."""

    def setUp(self):
        _CHAOS_HOOKS.clear()
        # Make getActiveWindow return WRONG title to simulate focus loss
        mock_win = MagicMock()
        mock_win.title = "VS Code"
        _mock_pygetwindow.getActiveWindow.return_value = mock_win
        _mock_pygetwindow.getWindowsWithTitle.return_value = []

    def tearDown(self):
        _CHAOS_HOOKS.clear()

    def test_chaos_hook_on_safe_hotkey_aborts_keypress(self):
        """
        When chaos hook fires for safe_hotkey and focus is wrong,
        FocusLostError must be raised BEFORE pyautogui.hotkey is called.
        """
        _side_effects = {"called": False}
        def _chaos():
            _side_effects["called"] = True  # hook fires

        _CHAOS_HOOKS["safe_hotkey"] = _chaos
        _mock_pyautogui.hotkey.reset_mock()

        with self.assertRaises(FocusLostError):
            safe_hotkey("Paint", "ctrl", "a")

        # Chaos hook MUST have fired
        self.assertTrue(_side_effects["called"])
        # pyautogui.hotkey MUST NOT have been called (no key leaked)
        _mock_pyautogui.hotkey.assert_not_called()

    def test_chaos_hook_on_safe_click_aborts_click(self):
        """Focus lost before safe_click — no click should be sent."""
        _CHAOS_HOOKS["safe_click"] = lambda: None  # no-op hook; focus loss comes from mock
        _mock_pyautogui.click.reset_mock()

        with self.assertRaises(FocusLostError):
            safe_click(100, 200, "Paint")

        _mock_pyautogui.click.assert_not_called()


class TestAuditLogCapture(unittest.TestCase):
    """Verify the audit log records both success and failure actions."""

    def setUp(self):
        _CHAOS_HOOKS.clear()
        # Make focus succeed
        mock_win = MagicMock()
        mock_win.title = "Untitled - Paint"
        _mock_pygetwindow.getActiveWindow.return_value = mock_win

    def test_success_logged(self):
        """A successful safe_hotkey call must appear in the audit log."""
        initial_len = len(get_audit_log())
        safe_hotkey("Paint", "ctrl", "z")
        log = get_audit_log()
        self.assertGreater(len(log), initial_len)
        last = log[-1]
        self.assertEqual(last["action"], "safe_hotkey")
        self.assertEqual(last["window"], "Paint")
        self.assertTrue(last["success"])

    def test_failure_logged_with_error(self):
        """When pyautogui.hotkey raises, the failure must be logged with the error message."""
        _mock_pyautogui.hotkey.side_effect = RuntimeError("simulated failure")
        try:
            safe_hotkey("Paint", "ctrl", "z")
        except RuntimeError:
            pass
        finally:
            _mock_pyautogui.hotkey.side_effect = None

        log = get_audit_log()
        failures = [e for e in log if not e["success"] and e["action"] == "safe_hotkey"]
        self.assertTrue(len(failures) > 0)
        self.assertIn("simulated failure", failures[-1]["error"])


class TestPluginRegistry(unittest.TestCase):
    """Verify the ApplicationAgent plugin registry (register_capability) works correctly."""

    def test_register_and_dispatch(self):
        """A registered capability must be callable via execute()."""
        from agents.application_agent import ApplicationAgent

        _called = {"with": None}

        def _my_handler(**kwargs):
            _called["with"] = kwargs
            return {"success": True, "custom": True}

        ApplicationAgent.register_capability("my_custom_action", _my_handler)

        agent = ApplicationAgent()
        result = agent.execute("my_custom_action", {"param1": "value1"})

        self.assertTrue(result["success"])
        self.assertTrue(result["custom"])
        self.assertEqual(_called["with"], {"param1": "value1"})

    def test_unknown_action_returns_error(self):
        """Dispatching an unknown action must return a failure dict, not raise."""
        from agents.application_agent import ApplicationAgent
        agent = ApplicationAgent()
        result = agent.execute("nonexistent_action_xyz", {})
        self.assertFalse(result["success"])
        self.assertIn("Unknown action", result["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
