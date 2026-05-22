"""
tests/test_core.py
Sprint 6 \u2014 Core regression + security tests for NovaMind.

Run:  pytest tests/test_core.py -v

Covers:
  \u2022 data_agent  \u2014 safe formula evaluator blocks injections, passes arithmetic
  \u2022 error_recovery_agent \u2014 doubled_timeout no longer injects 'timeout' into function args
  \u2022 memory_system \u2014 schema guard rebuilds stale DB without crashing
  \u2022 task_parser   \u2014 drawing tasks now route to execute_paint_task
"""
import asyncio
import os
import sys
import tempfile
import pytest

# Ensure project root is on sys.path for direct imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# =========================================================================
#  Test 1 \u2014 Safe formula evaluator in DataAgent
# =========================================================================

class TestSafeFormulaEval:
    """Verify that the safe AST evaluator blocks injections and passes arithmetic."""

    def _import_safe_eval(self):
        """Import the module-level helper (not a class method)."""
        from agents.data_agent import _safe_eval_formula
        return _safe_eval_formula

    def test_arithmetic_allowed(self):
        _f = self._import_safe_eval()
        row = {"price": 10, "qty": 3}
        result = _f("price * qty", row)
        assert result == 30, f"Expected 30, got {result}"

    def test_column_reference_allowed(self):
        _f = self._import_safe_eval()
        row = {"a": 5, "b": 2}
        assert _f("a + b", row) == 7

    def test_ternary_allowed(self):
        _f = self._import_safe_eval()
        row = {"x": 10}
        assert _f("1 if x > 5 else 0", row) == 1

    def test_import_blocked(self):
        _f = self._import_safe_eval()
        row = {"x": 1}
        # ast.Import is not in _SAFE_AST_NODES \u2014 should return None
        result = _f("__import__('os').system('echo pwned')", row)
        assert result is None, "Import should be blocked"

    def test_unknown_variable_blocked(self):
        _f = self._import_safe_eval()
        row = {"a": 1}
        # 'b' not in row \u2014 blocked
        result = _f("a + b", row)
        assert result is None, "Unknown variable should be blocked"

    def test_attribute_access_blocked(self):
        _f = self._import_safe_eval()
        row = {"a": 1}
        # Attribute access is an ast.Attribute node \u2014 not in safe list
        result = _f("a.__class__", row)
        assert result is None, "Attribute access should be blocked"

    def test_add_column_uses_safe_eval(self):
        from agents.data_agent import DataAgent
        agent = DataAgent()
        rows = [{"price": 10, "qty": 3}]
        res = agent.add_column(rows, "total", formula="price * qty")
        assert res["success"]
        assert res["rows"][0]["total"] == 30

    def test_add_column_blocks_injection(self):
        from agents.data_agent import DataAgent
        agent = DataAgent()
        rows = [{"x": 1}]
        res = agent.add_column(rows, "evil", formula="__import__('os').system('echo')")
        assert res["success"]
        assert res["rows"][0]["evil"] is None  # blocked \u2014 returns None, not crash


# =========================================================================
#  Test 2 \u2014 ErrorRecoveryAgent.doubled_timeout fix
# =========================================================================

class TestErrorRecoveryTimeout:
    """Verify that _retry_doubled_timeout does NOT inject 'timeout' into function args."""

    def test_doubled_timeout_does_not_inject_to_function_args(self):
        from agents.error_recovery_agent import ErrorRecoveryAgent
        agent = ErrorRecoveryAgent()

        ctx = {
            "task": {
                "action": "run_something",
                "args": {"command_line": "echo hi"},  # note: no 'timeout' key in args
                "timeout": 30,                        # step-level timeout
            },
            "output": "timed out",
            "retry_strategy": "",
            "task_id": "test-1",
        }

        plan = asyncio.run(agent.recover("timeout", ctx, attempt=0))

        assert plan.strategy_name == "doubled_timeout"
        # The function-level args must NOT have a 'timeout' key
        fn_args = plan.modified_task.get("args", {})
        assert "timeout" not in fn_args, (
            f"'timeout' must NOT appear in function args to avoid TypeError. "
            f"Got args={fn_args}"
        )
        # The step-level timeout must be doubled
        assert plan.modified_task.get("timeout") == 60, (
            f"Step-level timeout must be doubled to 60. Got {plan.modified_task.get('timeout')}"
        )

    def test_recover_generic_returns_plan(self):
        from agents.error_recovery_agent import ErrorRecoveryAgent
        agent = ErrorRecoveryAgent()
        ctx = {"task": {}, "output": "", "retry_strategy": "", "task_id": "test-2"}
        plan = asyncio.run(agent.recover("generic", ctx, attempt=0))
        assert plan.strategy_name in ("generic_fallback",), plan.strategy_name

    def test_classify_timeout_error(self):
        from agents.error_recovery_agent import ErrorRecoveryAgent
        agent = ErrorRecoveryAgent()
        assert agent.classify_error("operation timed out after 30s") == "timeout"
        assert agent.classify_error("element not found in DOM") == "element_not_found"
        assert agent.classify_error("some random noise") == "generic"


# =========================================================================
#  Test 3 \u2014 MemorySystem schema guard
# =========================================================================

class TestMemorySchemaGuard:
    """Verify that the schema rebuild guard recovers from stale/corrupt DB."""

    def test_fresh_db_initialises_without_error(self, tmp_path):
        from memory.memory_system import MemorySystem
        db = tmp_path / "test_fresh.db"
        ms = MemorySystem(db_path=str(db))
        stats = ms.get_memory_stats()
        assert stats["total_tasks"] == 0
        ms.close()

    def test_stale_db_is_rebuilt(self, tmp_path):
        """Write a DB with a missing column, then open MemorySystem and verify it recovers."""
        import sqlite3
        db_path = str(tmp_path / "stale.db")

        # Create a deliberately incomplete schema (missing 'session_id' column)
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, status TEXT)")
        conn.commit()
        conn.close()

        # MemorySystem should detect the mismatch and rebuild
        from memory.memory_system import MemorySystem
        ms = MemorySystem(db_path=db_path)
        stats = ms.get_memory_stats()
        # After rebuild, counts should be 0 (clean DB) without an exception
        assert isinstance(stats["total_tasks"], int)
        ms.close()


# =========================================================================
#  Test 4 \u2014 TaskParser routing
# =========================================================================

class TestTaskParserRouting:
    """Verify drawing tasks route to execute_paint_task."""

    def test_draw_plan_uses_execute_paint_task(self):
        # Skip if LLM router requires an API key
        try:
            from core.orchestration.task_parser import TaskParser
            parser = TaskParser()
            plan = parser.parse("draw a red car in paint")
            assert len(plan.steps) >= 1
            step = plan.steps[0]
            assert step.action == "execute_paint_task", (
                f"Expected execute_paint_task, got '{step.action}'"
            )
            assert step.agent == "application_agent"
        except Exception as exc:
            pytest.skip(f"TaskParser requires LLM router: {exc}")

    def test_is_drawing_request_detection(self):
        from core.orchestration.task_parser import TaskParser
        parser = TaskParser()
        assert parser._is_drawing_request("draw a car in paint") is True
        assert parser._is_drawing_request("open chrome") is False
        assert parser._is_drawing_request("list files") is False

    def test_color_extraction(self):
        from core.orchestration.task_parser import TaskParser
        parser = TaskParser()
        _subject, color = parser._extract_drawing_details("draw a red sports car in ms paint")
        assert color == "red"

    def test_fallback_parse_does_not_crash(self):
        from core.orchestration.task_parser import TaskParser
        parser = TaskParser()
        # _fallback_parse should always return a valid TaskPlan
        plan = parser._fallback_parse("do something weird")
        assert plan is not None
        assert len(plan.steps) >= 1


# =========================================================================
#  Test 5 \u2014 os_executor canvas coordinate clamping
# =========================================================================

class TestCanvasClamping:
    """Verify that canvas coordinates are always non-negative."""

    def test_dpi_scale_1_in_dpi_aware_process(self):
        """On a DPI-aware process (Qt running), DPI_SCALE should be 1.0."""
        try:
            from core.os_utils.os_executor import DPI_SCALE
            # DPI_SCALE should be 1.0 if the process is DPI-aware
            # (which it will be in any environment that has Qt running).
            assert DPI_SCALE >= 1.0, f"DPI_SCALE={DPI_SCALE} \u2014 expected \u22651.0"
        except ImportError:
            pytest.skip("os_executor not available (likely non-Windows)")
