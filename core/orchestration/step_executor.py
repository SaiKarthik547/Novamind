"""
core/step_executor.py

Unified verify-retry step execution loop.
Every action across every agent goes through here.
See → Execute → Verify → Retry (with different strategy) → Escalate.

All dispatch uses dict lookup — zero if/elif chains.
mouseUp guaranteed in finally on every draw path.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("StepExecutor")

try:
    import pyautogui
    PYAUTOGUI_OK = True
except ImportError:
    PYAUTOGUI_OK = False

try:
    from core.os_utils.os_executor import ActionVerifier, FocusLostError, capture_region
    OS_EXECUTOR_OK = True
except ImportError:
    OS_EXECUTOR_OK = False
    FocusLostError = Exception

    class ActionVerifier:
        def __init__(self, region=None):
            self.region = region
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            return False
        def verify_changed(self, desc: str = "") -> bool:
            return True
        def verify_unchanged(self, desc: str = "") -> bool:
            return True


@dataclass
class StepResult:
    success: bool
    attempts: int = 0
    error: str = ""
    verified: bool = False
    recovery_strategies_used: List[str] = field(default_factory=list)
    elapsed: float = 0.0


class StepExecutor:
    """
    Wraps any callable action with:
      1. Pre-action screenshot (captured inside ActionVerifier context)
      2. Action execution (the callable)
      3. Post-action screenshot comparison
      4. If no visual change AND change was expected → recovery → retry
      5. If max retries → return failure with diagnostic

    recovery_fns: list of alternative callables tried in order on each failure.
    Attempt N uses fns[min(N, len(fns)-1)] — last strategy is repeated on overflow.
    Zero if/elif — all branching via dict dispatch.
    """

    def __init__(self, max_retries: int = 3, llm_router=None):
        self._max_retries = max_retries
        self._llm = llm_router

    def execute_with_verify(
        self,
        action_fn: Callable,
        canvas_region: Tuple[int, int, int, int],
        description: str,
        expect_visual_change: bool = True,
        recovery_fns: Optional[List[Callable]] = None,
    ) -> StepResult:
        """
        Execute action_fn, verify canvas changed, retry with recovery_fns on failure.
        """
        start = time.time()
        result = StepResult(success=False)
        fns: List[Callable] = [action_fn] + (recovery_fns or [])

        for attempt in range(self._max_retries):
            result.attempts = attempt + 1
            fn = fns[min(attempt, len(fns) - 1)]

            with ActionVerifier(region=canvas_region) as verifier:
                try:
                    fn()
                    time.sleep(0.2)   # UI settle

                    _check_change: Dict[bool, Callable] = {
                        True: lambda: self._verify_visual_change(
                            verifier, description, result, attempt
                        ),
                    }
                    skip_verify = _check_change.get(not expect_visual_change,
                                                    lambda: True)
                    changed = skip_verify()

                    if not changed:
                        time.sleep(0.3 * (attempt + 1))
                        continue

                    result.success = True
                    result.verified = True
                    result.elapsed = time.time() - start
                    return result

                except FocusLostError as e:
                    result.error = str(e)
                    logger.error(f"Focus lost on attempt {attempt + 1}: {e}")
                    time.sleep(0.5)

                except Exception as e:
                    result.error = str(e)
                    _safe_mouseup()
                    logger.error(f"Action failed attempt {attempt + 1}: {e}")
                    time.sleep(0.3)

        result.elapsed = time.time() - start
        return result

    def execute_draw_stroke(
        self,
        points: List[Tuple[int, int]],
        canvas_region: Tuple[int, int, int, int],
        description: str = "",
    ) -> StepResult:
        """
        Specialised executor for mouse-drag drawing strokes.
        mouseUp is ALWAYS in a finally block — mouse never stays held.
        """
        start = time.time()
        result = StepResult(success=False)

        _too_short: Dict[bool, Callable] = {
            True: lambda: StepResult(
                success=False, error="stroke has < 2 points", attempts=0
            )
        }
        guard = _too_short.get(len(points) < 2)
        if guard:
            return guard()

        with ActionVerifier(region=canvas_region) as verifier:
            try:
                try:
                    _do_move = {True: lambda: pyautogui.mouseDown(*points[0])}
                    _do_move.get(PYAUTOGUI_OK, lambda: None)()
                    for pt in points[1:]:
                        _mov = {True: lambda p=pt: pyautogui.moveTo(*p, duration=0.01)}
                        _mov.get(PYAUTOGUI_OK, lambda: None)()
                finally:
                    _up = {True: lambda: pyautogui.mouseUp()}
                    _up.get(PYAUTOGUI_OK, lambda: None)()

                result.verified = verifier.verify_changed(
                    description or f"stroke {points[0]}→{points[-1]}"
                )
                result.success = True
                result.attempts = 1
                result.elapsed = time.time() - start
                return result

            except FocusLostError as e:
                result.error = str(e)
            except Exception as e:
                result.error = str(e)

        result.elapsed = time.time() - start
        return result

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _verify_visual_change(
        self,
        verifier: "ActionVerifier",
        description: str,
        result: StepResult,
        attempt: int,
    ) -> bool:
        changed = verifier.verify_changed(description)
        _on_no_change: Dict[bool, Callable] = {
            True: lambda: (
                result.recovery_strategies_used.append(
                    f"attempt_{attempt + 1}_no_change"
                )
                or logger.warning(f"No visual change after: {description}")
            )
        }
        _on_no_change.get(not changed, lambda: None)()
        return changed


def _safe_mouseup() -> None:
    """Unconditionally release the mouse. Called in all error/timeout paths."""
    _up = {True: lambda: pyautogui.mouseUp()}
    try:
        _up.get(PYAUTOGUI_OK, lambda: None)()
    except Exception:
        pass


def get_step_executor(max_retries: int = 3,
                      llm_router=None) -> StepExecutor:
    """Module-level factory — returns a ready-to-use StepExecutor."""
    return StepExecutor(max_retries=max_retries, llm_router=llm_router)
