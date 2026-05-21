"""
ErrorRecoveryAgent — Strategy-pattern error recovery.
Receives failed task + error context from VerifierAgent.
Each error type maps to an ordered list of recovery strategies.
Zero if-else in dispatch — O(1) strategy lookup + attempt indexing.
Pattern: STRATUS multi-agent SRE system (NeurIPS 2025).
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable, Awaitable, Dict, List, Optional

from core.base_agent import BaseAgent

logger = logging.getLogger("ErrorRecoveryAgent")


@dataclass
class RecoveryContext:
    original_task: Dict
    error_type: str
    tool_output: Any
    retry_strategy: str
    attempt_number: int
    task_id: str = ""


@dataclass
class RecoveryPlan:
    strategy_name: str
    modified_task: Dict
    description: str
    escalate: bool = False
    escalation_context: Dict = None


async def _try_alternative_selector(ctx: RecoveryContext) -> RecoveryPlan:
    args = dict(ctx.original_task.get("args", {}))
    args["use_aria_label"] = True
    args["selector_strategy"] = "aria-label,text-content,role"
    return RecoveryPlan(
        strategy_name="alternative_selector",
        modified_task={**ctx.original_task, "args": args},
        description="Retry with aria-label / text-content selector strategy",
    )


async def _try_visual_location(ctx: RecoveryContext) -> RecoveryPlan:
    args = dict(ctx.original_task.get("args", {}))
    args["use_vision_fallback"] = True
    args["vision_confidence_threshold"] = 0.75
    return RecoveryPlan(
        strategy_name="visual_location",
        modified_task={**ctx.original_task, "args": args},
        description="Screenshot + VisionAgent visual element location",
    )


async def _try_pyautogui_fallback(ctx: RecoveryContext) -> RecoveryPlan:
    args = dict(ctx.original_task.get("args", {}))
    args["tool_override"] = "pyautogui_click_by_vision"
    return RecoveryPlan(
        strategy_name="pyautogui_fallback",
        modified_task={**ctx.original_task, "args": args},
        description="PyAutoGUI click using VisionAgent-supplied coordinates",
    )


async def _retry_doubled_timeout(ctx: RecoveryContext) -> RecoveryPlan:
    """Retry with a doubled step-level timeout. Does NOT inject 'timeout' into
    function parameters (which would crash agents that don't accept it)."""
    # Read timeout from the step metadata, not the function args.
    old_timeout = ctx.original_task.get("timeout", 30)
    # Return a task copy with timeout at the step level only.
    modified = dict(ctx.original_task)
    modified["timeout"] = old_timeout * 2   # step timeout — not a function kwarg
    # args must remain unchanged so agent functions don’t receive an unexpected kwarg.
    return RecoveryPlan(
        strategy_name="doubled_timeout",
        modified_task=modified,
        description=f"Retry with step timeout doubled to {old_timeout * 2}s",
    )


async def _break_into_smaller_steps(ctx: RecoveryContext) -> RecoveryPlan:
    args = dict(ctx.original_task.get("args", {}))
    args["chunk_size"] = "small"
    args["max_steps_per_chunk"] = 3
    return RecoveryPlan(
        strategy_name="smaller_steps",
        modified_task={**ctx.original_task, "args": args},
        description="Break task into smaller atomic steps",
    )


async def _try_alternative_tool(ctx: RecoveryContext) -> RecoveryPlan:
    args = dict(ctx.original_task.get("args", {}))
    args["fallback_tool"] = "requests_http"
    return RecoveryPlan(
        strategy_name="alternative_tool",
        modified_task={**ctx.original_task, "args": args},
        description="Switch to alternative tool (e.g. requests instead of Playwright)",
    )


async def _fix_command_syntax(ctx: RecoveryContext) -> RecoveryPlan:
    args = dict(ctx.original_task.get("args", {}))
    err = str(ctx.tool_output)
    cmd = args.get("command", "")
    if cmd.startswith("rm ") and not cmd.startswith("rm -"):
        args["command"] = cmd.replace("rm ", "rm -f ", 1)
    args["auto_fix_syntax"] = True
    args["error_context"] = err[:200]
    return RecoveryPlan(
        strategy_name="fix_command_syntax",
        modified_task={**ctx.original_task, "args": args},
        description="Fix command syntax based on error message",
    )


async def _try_equivalent_command(ctx: RecoveryContext) -> RecoveryPlan:
    args = dict(ctx.original_task.get("args", {}))
    args["use_equivalent_command"] = True
    return RecoveryPlan(
        strategy_name="equivalent_command",
        modified_task={**ctx.original_task, "args": args},
        description="Try equivalent shell command with different flags",
    )


async def _use_python_subprocess(ctx: RecoveryContext) -> RecoveryPlan:
    args = dict(ctx.original_task.get("args", {}))
    args["force_python_subprocess"] = True
    return RecoveryPlan(
        strategy_name="python_subprocess",
        modified_task={**ctx.original_task, "args": args},
        description="Use Python subprocess instead of direct shell command",
    )


async def _reinject_schema_and_retry(ctx: RecoveryContext) -> RecoveryPlan:
    args = dict(ctx.original_task.get("args", {}))
    args["reinject_schema"] = True
    return RecoveryPlan(
        strategy_name="reinject_schema",
        modified_task={**ctx.original_task, "args": args},
        description="Re-inject output schema definition into LLM prompt",
    )


async def _add_output_examples(ctx: RecoveryContext) -> RecoveryPlan:
    args = dict(ctx.original_task.get("args", {}))
    args["include_output_examples"] = True
    return RecoveryPlan(
        strategy_name="output_examples",
        modified_task={**ctx.original_task, "args": args},
        description="Add concrete output format examples to LLM prompt",
    )


async def _use_lower_temperature(ctx: RecoveryContext) -> RecoveryPlan:
    args = dict(ctx.original_task.get("args", {}))
    args["temperature"] = 0.1
    args["force_constrained_model"] = True
    return RecoveryPlan(
        strategy_name="lower_temperature",
        modified_task={**ctx.original_task, "args": args},
        description="Use temperature=0.1 + more constrained model",
    )


async def _reset_paint_and_retry(ctx: RecoveryContext) -> RecoveryPlan:
    args = dict(ctx.original_task.get("args", {}))
    args["force_close_paint_first"] = True
    args["fresh_paint_window"] = True
    return RecoveryPlan(
        strategy_name="reset_paint",
        modified_task={**ctx.original_task, "args": args},
        description="Close all Paint windows, reopen, retry with fresh state",
    )


async def _geometric_drawing_fallback(ctx: RecoveryContext) -> RecoveryPlan:
    args = dict(ctx.original_task.get("args", {}))
    args["use_geometric_fallback"] = True
    args["hardcoded_path_sequence"] = True
    return RecoveryPlan(
        strategy_name="geometric_fallback",
        modified_task={**ctx.original_task, "args": args},
        description="Use pre-programmed geometric pyautogui path sequence",
    )


async def _use_simpler_shape(ctx: RecoveryContext) -> RecoveryPlan:
    args = dict(ctx.original_task.get("args", {}))
    args["simplify_drawing"] = True
    args["fallback_to_basic_shapes"] = True
    return RecoveryPlan(
        strategy_name="simpler_shape",
        modified_task={**ctx.original_task, "args": args},
        description="Use simpler geometric shapes as drawing fallback",
    )


async def _generic_fallback(ctx: RecoveryContext) -> RecoveryPlan:
    return RecoveryPlan(
        strategy_name="generic_fallback",
        modified_task=ctx.original_task,
        description="Retry with same approach (no modification)",
    )


async def _escalate(ctx: RecoveryContext) -> RecoveryPlan:
    return RecoveryPlan(
        strategy_name="escalate",
        modified_task=ctx.original_task,
        description="All strategies exhausted — escalate to user",
        escalate=True,
        escalation_context={
            "task": ctx.original_task,
            "error_type": ctx.error_type,
            "attempts": ctx.attempt_number,
            "last_output": str(ctx.tool_output)[:500],
        },
    )


StrategyFn = Callable[[RecoveryContext], Awaitable[RecoveryPlan]]

RECOVERY_STRATEGIES: Dict[str, List[StrategyFn]] = {
    "element_not_found": [
        _try_alternative_selector,
        _try_visual_location,
        _try_pyautogui_fallback,
    ],
    "timeout": [
        _retry_doubled_timeout,
        _break_into_smaller_steps,
        _try_alternative_tool,
    ],
    "command_failed": [
        _fix_command_syntax,
        _try_equivalent_command,
        _use_python_subprocess,
    ],
    "llm_schema_mismatch": [
        _reinject_schema_and_retry,
        _add_output_examples,
        _use_lower_temperature,
    ],
    "paint_drawing_failed": [
        _reset_paint_and_retry,
        _geometric_drawing_fallback,
        _use_simpler_shape,
    ],
    "generic": [
        _generic_fallback,
        _break_into_smaller_steps,
        _escalate,
    ],
}

MAX_RETRIES_PER_NODE = 3


class ErrorRecoveryAgent(BaseAgent):
    """
    Receives failed tasks from VerifierAgent.
    Selects recovery strategy by error_type + attempt_number.
    O(1) lookup: error_type → strategy list → index by attempt.
    Zero if-else in the dispatch path.
    """

    def __init__(self, event_bus=None, memory_system=None):
        super().__init__()
        self.event_bus = event_bus
        self.memory = memory_system

        self.handlers = {
            "classify": lambda error_message="": {
                "success": True,
                "error_type": self.classify_error(error_message),
            },
            "recover": self._run_recover_sync,
        }

    async def recover(self, error_type: str, context: Dict,
                      attempt: int) -> RecoveryPlan:
        """
        Main recovery entry point.
        error_type → strategy list → strategies[min(attempt, len-1)]
        Direct call. No branching in dispatch.
        """
        strategies = RECOVERY_STRATEGIES.get(
            error_type, RECOVERY_STRATEGIES["generic"]
        )
        strategy_fn = strategies[min(attempt, len(strategies) - 1)]

        ctx = RecoveryContext(
            original_task=context.get("task", {}),
            error_type=error_type,
            tool_output=context.get("output", ""),
            retry_strategy=context.get("retry_strategy", ""),
            attempt_number=attempt,
            task_id=context.get("task_id", ""),
        )

        plan = await strategy_fn(ctx)

        if self.event_bus:
            self.event_bus.emit_sync("task_retrying", {
                "task_id": ctx.task_id,
                "error_type": error_type,
                "strategy": plan.strategy_name,
                "attempt": attempt,
            })

        logger.info(
            f"[Recovery] {error_type} attempt={attempt} "
            f"→ {plan.strategy_name}: {plan.description}"
        )

        if plan.escalate and self.event_bus:
            self.event_bus.emit_sync(
                "human_escalation_required", plan.escalation_context or {}
            )

        return plan

    def classify_error(self, error_message: str) -> str:
        """
        Classify error string into error_type key for RECOVERY_STRATEGIES.
        frozenset membership — O(1) per pattern group.
        """
        em = error_message.lower()

        ELEMENT_KEYWORDS  = frozenset({"element", "not found", "selector",
                                        "locator", "no element"})
        TIMEOUT_KEYWORDS  = frozenset({"timeout", "timed out", "deadline",
                                        "exceeded"})
        COMMAND_KEYWORDS  = frozenset({"command", "returncode", "exit code",
                                        "syntax error", "bash"})
        SCHEMA_KEYWORDS   = frozenset({"json", "schema", "parse", "decode",
                                        "invalid", "unexpected"})
        PAINT_KEYWORDS    = frozenset({"paint", "draw", "canvas", "stroke",
                                        "mspaint"})

        KEYWORD_TO_TYPE = {
            "element_not_found": ELEMENT_KEYWORDS,
            "timeout":           TIMEOUT_KEYWORDS,
            "command_failed":    COMMAND_KEYWORDS,
            "llm_schema_mismatch": SCHEMA_KEYWORDS,
            "paint_drawing_failed": PAINT_KEYWORDS,
        }

        for error_type, keywords in KEYWORD_TO_TYPE.items():
            if any(kw in em for kw in keywords):
                return error_type
        return "generic"

    def _run_recover_sync(self, **p) -> Dict:
        """
        Run the async recovery coroutine from a sync context.
        Thread-pool trick: if a loop happens to be running in this thread
        (shouldn't be, but defensive), submit to fresh executor thread.
        """
        try:
            loop = asyncio.get_running_loop()
            running = loop.is_running()
        except RuntimeError:
            running = False

        import concurrent.futures as _cf
        _strategies: Dict[bool, Any] = {
            True:  lambda c: _cf.ThreadPoolExecutor(
                max_workers=1
            ).submit(asyncio.run, c).result(timeout=60),
            False: lambda c: asyncio.run(c),
        }
        return _strategies[running](self._sync_recover(p))

    async def _sync_recover(self, params: Dict) -> Dict:
        plan = await self.recover(
            error_type=params.get("error_type", "generic"),
            context=params.get("context", {}),
            attempt=params.get("attempt", 0),
        )
        return {
            "success": True,
            "strategy": plan.strategy_name,
            "description": plan.description,
            "escalate": plan.escalate,
            "modified_task": plan.modified_task,
        }
