"""
tests/test_kernel_convergence.py
Tests for Level 0-2.5 architectural convergence components.
Validates: CapabilityRegistry, KernelExecutionFacade, LegacyUIAdapter,
           IntentExecutionState, VerificationTaxonomy.
"""

import unittest
from unittest.mock import patch, MagicMock

from core.execution.capability_registry import (
    CAPABILITY_REGISTRY,
    DeterminismClass,
    ReplayPolicy,
    AuthorityLevel,
)
from core.execution.intent_execution_state import (
    IntentExecutionState,
    IntentStateMachine,
    IntentStateError,
    TERMINAL_STATES,
)
from core.execution.verification_taxonomy import (
    VerificationMode,
    validate_verification_mode,
)


# ─────────────────────────────────────────────────────────────────────────────
#  CapabilityRegistry
# ─────────────────────────────────────────────────────────────────────────────

class TestCapabilityRegistry(unittest.TestCase):

    def test_known_capability_returns_definition(self):
        defn = CAPABILITY_REGISTRY.get("filesystem.read")
        self.assertIsNotNone(defn)
        self.assertEqual(defn.determinism_class, DeterminismClass.DETERMINISTIC)

    def test_unknown_capability_returns_none(self):
        self.assertIsNone(CAPABILITY_REGISTRY.get("nonexistent.action"))

    def test_require_known_capability_succeeds(self):
        defn = CAPABILITY_REGISTRY.require("process.spawn")
        self.assertEqual(defn.capability_name, "process.spawn")

    def test_require_unknown_capability_raises(self):
        with self.assertRaises(PermissionError):
            CAPABILITY_REGISTRY.require("agent.subprocess_raw")

    def test_ui_capabilities_are_non_deterministic(self):
        defn = CAPABILITY_REGISTRY.require("ui.mouse_click")
        self.assertEqual(defn.determinism_class, DeterminismClass.NON_DETERMINISTIC)
        self.assertEqual(defn.replay_policy, ReplayPolicy.SKIP)
        self.assertTrue(defn.requires_user_focus)
        self.assertFalse(defn.allows_background_execution)

    def test_ui_capabilities_require_legacy_bridge(self):
        defn = CAPABILITY_REGISTRY.require("ui.hotkey")
        self.assertEqual(defn.authority_level, AuthorityLevel.LEGACY_BRIDGE)

    def test_filesystem_write_is_permanent(self):
        defn = CAPABILITY_REGISTRY.require("filesystem.write")
        self.assertTrue(defn.side_effect_permanent)

    def test_filesystem_read_is_not_permanent(self):
        defn = CAPABILITY_REGISTRY.require("filesystem.read")
        self.assertFalse(defn.side_effect_permanent)

    def test_all_capabilities_have_valid_determinism_class(self):
        for name in CAPABILITY_REGISTRY.all_capabilities():
            defn = CAPABILITY_REGISTRY.require(name)
            self.assertIn(defn.determinism_class, DeterminismClass)

    def test_registry_is_singleton(self):
        from core.execution.capability_registry import CapabilityRegistry
        r1 = CapabilityRegistry()
        r2 = CapabilityRegistry()
        self.assertIs(r1, r2)


# ─────────────────────────────────────────────────────────────────────────────
#  IntentExecutionState
# ─────────────────────────────────────────────────────────────────────────────

class TestIntentExecutionState(unittest.TestCase):

    def test_valid_happy_path(self):
        sm = IntentStateMachine("test-intent-001")
        sm.transition(IntentExecutionState.QUEUED)
        sm.transition(IntentExecutionState.DISPATCHED)
        sm.transition(IntentExecutionState.RUNNING)
        sm.transition(IntentExecutionState.VERIFYING)
        sm.transition(IntentExecutionState.COMPLETED)
        self.assertEqual(sm.current(), IntentExecutionState.COMPLETED)
        self.assertTrue(sm.is_terminal())

    def test_valid_failure_compensation_path(self):
        sm = IntentStateMachine("test-intent-002")
        sm.transition(IntentExecutionState.QUEUED)
        sm.transition(IntentExecutionState.DISPATCHED)
        sm.transition(IntentExecutionState.RUNNING)
        sm.transition(IntentExecutionState.FAILED)
        sm.transition(IntentExecutionState.COMPENSATING)
        sm.transition(IntentExecutionState.COMPENSATED)
        self.assertTrue(sm.is_terminal())

    def test_illegal_transition_raises(self):
        sm = IntentStateMachine("test-intent-003")
        sm.transition(IntentExecutionState.QUEUED)
        with self.assertRaises(IntentStateError):
            sm.transition(IntentExecutionState.COMPLETED)  # Illegal skip

    def test_cannot_leave_terminal_state(self):
        sm = IntentStateMachine("test-intent-004")
        sm.transition(IntentExecutionState.REJECTED)
        with self.assertRaises(IntentStateError):
            sm.transition(IntentExecutionState.QUEUED)

    def test_abort_from_created(self):
        sm = IntentStateMachine("test-intent-005")
        sm.transition(IntentExecutionState.ABORTED)
        self.assertTrue(sm.is_terminal())

    def test_reject_from_created(self):
        sm = IntentStateMachine("test-intent-006")
        sm.transition(IntentExecutionState.REJECTED)
        self.assertTrue(sm.is_terminal())

    def test_history_is_recorded(self):
        sm = IntentStateMachine("test-intent-007")
        sm.transition(IntentExecutionState.QUEUED)
        sm.transition(IntentExecutionState.DISPATCHED)
        self.assertEqual(len(sm.history), 3)  # CREATED + QUEUED + DISPATCHED

    def test_all_terminal_states_have_no_outgoing_transitions(self):
        from core.execution.intent_execution_state import LEGAL_TRANSITIONS
        for state in TERMINAL_STATES:
            self.assertEqual(len(LEGAL_TRANSITIONS[state]), 0)


# ─────────────────────────────────────────────────────────────────────────────
#  VerificationTaxonomy
# ─────────────────────────────────────────────────────────────────────────────

class TestVerificationTaxonomy(unittest.TestCase):

    def test_strict_allowed_for_deterministic(self):
        validate_verification_mode("DETERMINISTIC", VerificationMode.STRICT_STATE_VERIFICATION)

    def test_strict_not_allowed_for_non_deterministic(self):
        with self.assertRaises(ValueError):
            validate_verification_mode("NON_DETERMINISTIC", VerificationMode.STRICT_STATE_VERIFICATION)

    def test_observational_allowed_for_semi_deterministic(self):
        validate_verification_mode("SEMI_DETERMINISTIC", VerificationMode.OBSERVATIONAL_VERIFICATION)

    def test_observational_not_allowed_for_deterministic(self):
        with self.assertRaises(ValueError):
            validate_verification_mode("DETERMINISTIC", VerificationMode.OBSERVATIONAL_VERIFICATION)

    def test_human_confirmed_only_for_non_deterministic(self):
        validate_verification_mode("NON_DETERMINISTIC", VerificationMode.HUMAN_CONFIRMED)

    def test_best_effort_allowed_for_all(self):
        for dc in ["DETERMINISTIC", "SEMI_DETERMINISTIC", "NON_DETERMINISTIC"]:
            validate_verification_mode(dc, VerificationMode.BEST_EFFORT)

    def test_none_allowed_for_deterministic(self):
        validate_verification_mode("DETERMINISTIC", VerificationMode.NONE)

    def test_none_not_allowed_for_non_deterministic(self):
        with self.assertRaises(ValueError):
            validate_verification_mode("NON_DETERMINISTIC", VerificationMode.NONE)


# ─────────────────────────────────────────────────────────────────────────────
#  KernelExecutionFacade
# ─────────────────────────────────────────────────────────────────────────────

class TestKernelExecutionFacade(unittest.TestCase):

    def test_unregistered_capability_is_rejected(self):
        from core.execution.kernel_facade import KernelExecutionFacade
        facade = KernelExecutionFacade()
        result = facade.dispatch("agent.raw_subprocess", {"cmd": "whoami"})
        self.assertFalse(result["success"])
        self.assertIn("not registered", result["error"])
        self.assertEqual(result["authority_origin"], "unsafe_runtime")

    def test_ui_capability_routes_to_legacy(self):
        from core.execution.kernel_facade import KernelExecutionFacade
        facade = KernelExecutionFacade()
        with patch("core.execution.kernel_facade.KernelExecutionFacade._route_legacy") as mock_legacy:
            mock_legacy.return_value = {"success": True}
            result = facade.dispatch("ui.mouse_click", {"x": 100, "y": 200})
            mock_legacy.assert_called_once()
            self.assertEqual(result["authority_origin"], "legacy_bridge")
            self.assertEqual(result["determinism_class"], "NON_DETERMINISTIC")

    def test_filesystem_capability_routes_to_adapter(self):
        from core.execution.kernel_facade import KernelExecutionFacade
        facade = KernelExecutionFacade()
        with patch("core.execution.kernel_facade.KernelExecutionFacade._route_adapter") as mock_adapter:
            mock_adapter.return_value = {"success": True, "content": "data"}
            result = facade.dispatch("filesystem.read", {"path": "/tmp/test.txt"})
            mock_adapter.assert_called_once()
            self.assertEqual(result["authority_origin"], "kernel")

    def test_result_always_contains_intent_metadata(self):
        from core.execution.kernel_facade import KernelExecutionFacade
        facade = KernelExecutionFacade()
        result = facade.dispatch("nonexistent.cap", {})
        self.assertIn("intent_id", result)
        self.assertIn("authority_origin", result)
        self.assertIn("duration_ms", result)


if __name__ == "__main__":
    unittest.main()
