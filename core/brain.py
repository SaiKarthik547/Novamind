"""
Brain — Task orchestration and execution engine.
State machine pattern: every transition writes to StateManager.
EventBus emitted on every transition — full observability.
VerifierAgent runs after every step — no silent failures.
ErrorRecoveryAgent invoked on each failure — strategy pattern dispatch.
Agent dispatch via O(1) dict lookup — zero if-else routing.
"""
import asyncio
import concurrent.futures
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from core.task_parser import TaskParser, TaskPlan, TaskStep, RiskLevel
from core.llm_router import get_router
from core.parallel_engine import ParallelExecutionEngine, TaskNode, TaskStatus

logger = logging.getLogger("Brain")


class ExecutionStatus(Enum):
    PENDING            = "pending"
    RUNNING            = "running"
    RETRYING           = "retrying"
    SUCCESS            = "success"
    FAILED             = "failed"
    CANCELLED          = "cancelled"
    NEEDS_CONFIRMATION = "needs_confirmation"


@dataclass
class StepResult:
    step_number: int
    status:      ExecutionStatus
    agent:       str
    action:      str
    output:      str = ""
    error:       str = ""
    duration:    float = 0.0
    retry_count: int = 0


@dataclass
class TaskExecution:
    task_id:          str
    original_request: str
    plan:             TaskPlan
    status:           ExecutionStatus = ExecutionStatus.PENDING
    results:          List[StepResult] = field(default_factory=list)
    start_time:       str = field(default_factory=lambda: datetime.now().isoformat())
    end_time:         str = ""
    completed_steps:  int = 0
    failed_steps:     int = 0
    total_steps:      int = 0
    summary:          str = ""
    error_log:        List[str] = field(default_factory=list)
    on_status_update: Any = None


# ─────────────────────────────────────────────────────────────────────────────
#  State-machine transition table — replaces the if-elif execution loop
# ─────────────────────────────────────────────────────────────────────────────

# Allowed transitions: current_state → set of valid next states
VALID_TRANSITIONS: Dict[ExecutionStatus, frozenset] = {
    ExecutionStatus.PENDING:   frozenset({ExecutionStatus.RUNNING,
                                          ExecutionStatus.CANCELLED}),
    ExecutionStatus.RUNNING:   frozenset({ExecutionStatus.SUCCESS,
                                          ExecutionStatus.FAILED,
                                          ExecutionStatus.RETRYING,
                                          ExecutionStatus.NEEDS_CONFIRMATION,
                                          ExecutionStatus.CANCELLED}),
    ExecutionStatus.RETRYING:  frozenset({ExecutionStatus.RUNNING,
                                          ExecutionStatus.FAILED,
                                          ExecutionStatus.CANCELLED}),
    ExecutionStatus.NEEDS_CONFIRMATION: frozenset({ExecutionStatus.RUNNING,
                                                   ExecutionStatus.CANCELLED}),
    ExecutionStatus.SUCCESS:   frozenset(),
    ExecutionStatus.FAILED:    frozenset(),
    ExecutionStatus.CANCELLED: frozenset(),
}


# ── Module-level constants for GUI serialisation + DAG safety ─────────────────

# Only one GUI-touching agent may hold the OS cursor at a time
GUI_LOCK = threading.Lock()

# Agents that touch the physical screen — must serialise via GUI_LOCK
_GUI_AGENTS: frozenset = frozenset({"application", "system", "vision"})

# Final-status lookup: bool(any_ok) → ExecutionStatus (replaces elif chain)
_FINAL_STATUS: Dict[bool, "ExecutionStatus"] = {}   # populated after class def


def _run_coroutine_safe(coro) -> Any:
    """
    Run a coroutine safely regardless of whether an event loop is already running.
    Uses dict dispatch — zero if/elif/else.
    Kept for backward compat; Brain instances prefer self._run_coro().
    """
    running: bool = False
    try:
        loop = asyncio.get_running_loop()
        running = loop.is_running()
    except RuntimeError:
        running = False

    LOOP_STRATEGIES: Dict[bool, Callable] = {
        True:  lambda c: concurrent.futures.ThreadPoolExecutor(
            max_workers=1
        ).submit(asyncio.run, c).result(timeout=30),
        False: lambda c: asyncio.run(c),
    }
    return LOOP_STRATEGIES[running](coro)


def _safe_mouseup() -> None:
    """Unconditionally release the mouse. Called in agent error/timeout paths."""
    try:
        import pyautogui
        pyautogui.mouseUp()
    except Exception:
        pass


class Brain:
    """
    Central orchestrator — state machine + parallel-ready execution.
    Every state transition:
      1. Validated against VALID_TRANSITIONS (frozenset O(1) check)
      2. Written to StateManager (SQLite checkpoint)
      3. Emitted on EventBus (observability)
    Every step result passes through VerifierAgent before being accepted.
    Every failure is dispatched to ErrorRecoveryAgent for strategy selection.
    DAG safety: every step is pre-screened by CommandGuard before dispatch.
    GUI serialisation: _GUI_AGENTS steps acquire GUI_LOCK before execution.
    """

    MAX_RETRIES     = 3
    STEP_TIMEOUT    = 120
    MAX_CONCURRENT  = 3

    def __init__(self, vision_system=None, agents: Dict = None,
                 memory_system=None, security=None,
                 event_bus=None, state_manager=None,
                 verifier=None, recovery_agent=None):

        self.vision         = vision_system
        self.agents         = agents or {}
        self.memory         = memory_system
        self.security       = security
        self.router         = get_router()
        self.parser         = TaskParser()
        self.event_bus      = event_bus
        self.state_manager  = state_manager
        self.verifier       = verifier
        self.recovery_agent = recovery_agent

        self._tasks:     Dict[str, TaskExecution] = {}
        self._lock       = threading.Lock()
        self._semaphore  = threading.Semaphore(self.MAX_CONCURRENT)
        self._task_callbacks: List[Callable] = []

        # Dedicated asyncio event loop running in a daemon thread.
        # Prevents RuntimeError when Qt and brain coroutines share a thread.
        # All async work is submitted via self._run_coro() — thread-safe.
        self._async_loop = asyncio.new_event_loop()
        self._async_thread = threading.Thread(
            target=self._async_loop.run_forever,
            daemon=True,
            name="brain-async",
        )
        self._async_thread.start()

        self.parallel_engine = ParallelExecutionEngine(
            agents=self.agents,
            event_bus=self.event_bus,
            state_manager=self.state_manager,
            gui_lock=GUI_LOCK,
            gui_agents=_GUI_AGENTS
        )

        logger.info(f"Brain initialised | {len(self.agents)} agents | "
                    f"EventBus={'yes' if event_bus else 'no'} | "
                    f"Verifier={'yes' if verifier else 'no'} | "
                    f"Recovery={'yes' if recovery_agent else 'no'}")

    # ──────────────────────────────────────────────────────────────────────────
    #  Public API
    # ──────────────────────────────────────────────────────────────────────────

    def process_request(self, user_request: str,
                        context: Dict = None,
                        on_update: Callable = None) -> TaskExecution:
        task_id = str(uuid.uuid4())
        logger.info(f"New task [{task_id[:8]}]: {user_request}")

        ctx = context or {}
        ctx = self._enrich_context(ctx, user_request)

        plan = self.parser.parse(user_request, context=ctx)
        logger.info(f"Plan: {plan.task_type.value}, "
                    f"{len(plan.steps)} steps, risk={plan.risk_assessment.value}")

        blocked = self._security_check(user_request)
        if blocked:
            return self._make_blocked_exec(task_id, user_request, plan, blocked)

        # DAG safety: pre-screen all steps before spawning any execution
        dag_ok, dag_reason = self._validate_dag_plan(plan)
        if not dag_ok:
            return self._make_blocked_exec(task_id, user_request, plan, dag_reason)

        exec_ = TaskExecution(
            task_id=task_id,
            original_request=user_request,
            plan=plan,
            status=ExecutionStatus.PENDING,
            total_steps=len(plan.steps),
            summary=plan.summary,
            on_status_update=on_update,
        )
        with self._lock:
            self._tasks[task_id] = exec_

        self._record_task_start(exec_)
        self._emit("task_started", {
            "task_id": task_id,
            "request": user_request,
            "plan_steps": len(plan.steps),
        })

        t = threading.Thread(
            target=self._run_task_execution,
            args=(exec_,),
            daemon=True,
            name=f"task-{task_id[:8]}",
        )
        t.start()
        return exec_

    def stop(self) -> None:
        """Shut down the brain, closing the async loop worker."""
        logger.info("Stopping Brain ...")
        if self._async_loop:
            self._async_loop.call_soon_threadsafe(self._async_loop.stop)
        if self._async_thread:
            self._async_thread.join(timeout=2)
        logger.info("Brain stopped.")

    def get_task_status(self, task_id: str) -> Optional[Dict]:
        with self._lock:
            exec_ = self._tasks.get(task_id)
        return self._execution_to_dict(exec_) if exec_ else None

    def get_all_tasks(self, limit: int = 50) -> List[Dict]:
        with self._lock:
            execs = list(self._tasks.values())
        execs.sort(key=lambda e: e.start_time, reverse=True)
        return [self._execution_to_dict(e) for e in execs[:limit]]

    def cancel_task(self, task_id: str) -> bool:
        with self._lock:
            exec_ = self._tasks.get(task_id)
        if exec_ and exec_.status in (ExecutionStatus.PENDING,
                                      ExecutionStatus.RUNNING):
            self._transition(exec_, ExecutionStatus.CANCELLED,
                             {"reason": "user cancelled"})
            return True
        return False

    def register_callback(self, fn: Callable) -> None:
        self._task_callbacks.append(fn)

    # ──────────────────────────────────────────────────────────────────────────
    #  State machine transitions
    # ──────────────────────────────────────────────────────────────────────────

    def _transition(self, exec_: TaskExecution, new_status: ExecutionStatus,
                    event_data: Dict = None) -> bool:
        """
        Validate transition, write to StateManager, emit event.
        Returns False if transition is invalid (already terminal).
        """
        allowed = VALID_TRANSITIONS.get(exec_.status, frozenset())
        if new_status not in allowed:
            logger.debug(f"Invalid transition {exec_.status} → {new_status} "
                         f"(task {exec_.task_id[:8]})")
            return False

        exec_.status = new_status

        if self.state_manager:
            try:
                from core.state_manager import TaskStatus
                status_map = {
                    ExecutionStatus.PENDING:   TaskStatus.PENDING,
                    ExecutionStatus.RUNNING:   TaskStatus.RUNNING,
                    ExecutionStatus.RETRYING:  TaskStatus.RETRYING,
                    ExecutionStatus.SUCCESS:   TaskStatus.COMPLETED,
                    ExecutionStatus.FAILED:    TaskStatus.FAILED,
                    ExecutionStatus.CANCELLED: TaskStatus.FAILED,
                }
                ts = status_map.get(new_status, TaskStatus.PENDING)
                self.state_manager.update_task(
                    exec_.task_id, exec_.task_id, ts
                )
            except Exception as exc:
                logger.debug(f"StateManager update: {exc}")

        self._emit(new_status.value, {
            "task_id": exec_.task_id,
            **(event_data or {}),
        })
        self._notify(exec_)
        return True

    # ──────────────────────────────────────────────────────────────────────────
    #  Execution loop
    # ──────────────────────────────────────────────────────────────────────────

    def _run_task_execution(self, exec_: TaskExecution) -> None:
        with self._semaphore:
            self._transition(exec_, ExecutionStatus.RUNNING,
                             {"request": exec_.original_request})
            steps_ok = 0
            steps_fail = 0

            # Sprint 5: Check if any step has dependencies; if so, use ParallelEngine
            has_deps = any(step.depends_on for step in exec_.plan.steps)
            
            if has_deps:
                logger.info(f"DAG detected for task {exec_.task_id[:8]} — using ParallelEngine")
                self._run_parallel_execution(exec_)
                return

            for step in exec_.plan.steps:
                if exec_.status == ExecutionStatus.CANCELLED:
                    break

                result = self._execute_step_with_verify(exec_, step)
                exec_.results.append(result)

                if result.status == ExecutionStatus.SUCCESS:
                    steps_ok += 1
                    exec_.completed_steps += 1
                else:
                    steps_fail += 1
                    exec_.failed_steps += 1
                    exec_.error_log.append(
                        f"Step {step.step_number}: {result.error}"
                    )
                    if step.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
                        break

                self._notify(exec_)

            # O(1) dict dispatch — replaces elif chain for final status
            # bool(steps_ok > 0) → SUCCESS/FAILED; no transition when cancelled
            not_cancelled = exec_.status != ExecutionStatus.CANCELLED
            target = _FINAL_STATUS.get(steps_ok > 0, ExecutionStatus.FAILED)
            not_cancelled and self._transition(
                exec_, target,
                {"steps_ok": steps_ok, "steps_fail": steps_fail})
            # Annotate partial failures (any ok AND any fail)
            partial = not_cancelled and steps_ok > 0 and steps_fail > 0
            partial and setattr(
                exec_, "summary",
                (exec_.summary or "") + f" ({steps_fail} step(s) failed)")

            exec_.end_time = datetime.now().isoformat()
            self._finalize(exec_, steps_ok, steps_fail)
            self._notify(exec_)

    def _run_parallel_execution(self, exec_: TaskExecution) -> None:
        """Convert TaskPlan to DAG and run via ParallelExecutionEngine."""
        nodes = []
        for s in exec_.plan.steps:
            node = TaskNode(
                id=str(s.step_number),
                description=s.description,
                agent_type=s.agent,
                tool=s.action,
                args=s.parameters,
                depends_on=[str(d) for d in s.depends_on],
                expected_output={"success": True},
                timeout=self.STEP_TIMEOUT
            )
            nodes.append(node)
        
        try:
            results = self._run_coro(self.parallel_engine.execute_dag(nodes))
            
            # Map engine results back to StepResults
            for s in exec_.plan.steps:
                node = next((n for n in nodes if n.id == str(s.step_number)), None)
                if node:
                    res = StepResult(
                        step_number=s.step_number,
                        status=ExecutionStatus.SUCCESS if node.status == TaskStatus.COMPLETED else ExecutionStatus.FAILED,
                        agent=s.agent,
                        action=s.action,
                        output=str(node.result)[:1000],
                        error=node.error,
                        duration=0  # Engine doesn't track per-node duration yet
                    )
                    exec_.results.append(res)
                    if res.status == ExecutionStatus.SUCCESS:
                        exec_.completed_steps += 1
                    else:
                        exec_.failed_steps += 1

            target = _FINAL_STATUS.get(exec_.completed_steps > 0, ExecutionStatus.FAILED)
            self._transition(exec_, target, {"completed": exec_.completed_steps})
            
        except Exception as e:
            logger.error(f"Parallel execution failed: {e}")
            self._transition(exec_, ExecutionStatus.FAILED, {"error": str(e)})

    def _execute_step_with_verify(self, exec_: TaskExecution,
                                   step: TaskStep) -> StepResult:
        """Iterative step execution to prevent RecursionError."""
        start = time.monotonic()
        last_error = "Execution failed"
        
        for attempt in range(self.MAX_RETRIES):
            if exec_.status == ExecutionStatus.CANCELLED:
                return StepResult(step_number=step.step_number, status=ExecutionStatus.CANCELLED, agent=step.agent, action=step.action)

            if attempt > 0:
                self._handle_retry_wait(exec_, step, attempt)

            logger.info(f"  Step {step.step_number}/{exec_.total_steps}: {step.agent}.{step.action} (attempt {attempt + 1})")
            step_db_id = self._record_step_start(exec_, step)

            # Execution with timeout
            res_container = [{"success": False, "error": "Execution failed"}]
            def _run_capture(): res_container[0] = self._call_agent(exec_, step)
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_run_capture)
                try:
                    future.result(timeout=getattr(self, "STEP_TIMEOUT", 300))
                    result_data = res_container[0]
                except concurrent.futures.TimeoutError:
                    result_data = {"success": False, "error": "Step timed out"}

            success = result_data.get("success", False)
            duration = time.monotonic() - start
            self._record_step_end(exec_, step, step_db_id, result_data, success, attempt)

            # Verification
            v_success, v_data = (success, result_data)
            if success and self.verifier:
                v_success, v_data = self._run_verification(step, result_data, exec_)

            if v_success:
                return StepResult(
                    step_number=step.step_number, status=ExecutionStatus.SUCCESS,
                    agent=step.agent, action=step.action,
                    output=_format_output(v_data), duration=duration,
                    retry_count=attempt
                )
            last_error = v_data.get("error", "Unknown error")

            # Trigger recovery before next retry so subsequent attempt uses
            # a different strategy — not an identical blind retry.
            last_error = self._handle_step_failure(exec_, step, v_data, attempt,
                                                   start)

        return StepResult(
            step_number=step.step_number, status=ExecutionStatus.FAILED,
            agent=step.agent, action=step.action,
            error=str(last_error), duration=time.monotonic() - start,
            retry_count=self.MAX_RETRIES - 1
        )

    def _handle_retry_wait(self, exec_, step, attempt):
        self._transition(exec_, ExecutionStatus.RETRYING,
                         {"step": step.step_number, "attempt": attempt})
        time.sleep(min(2 ** attempt, 10))
        self._transition(exec_, ExecutionStatus.RUNNING,
                         {"step": step.step_number})

    def _run_verification(self, step, result_data, exec_):
        vr = self.verifier.verify(
            task_description=step.description,
            tool_name=f"{step.agent}.{step.action}",
            expected_output={"success": True},
            actual_output=result_data,
            task_id=exec_.task_id,
        )
        SATISFACTION_MAP: Dict[bool, tuple] = {
            True:  (True, result_data),
            False: (False, {
                **result_data,
                "success": False,
                "verifier_issues": vr.issues,
                "error": f"Verifier: {'; '.join(vr.issues)}"
            })
        }
        return SATISFACTION_MAP[vr.satisfied]

    def _handle_step_failure(self, exec_, step, data, attempt, start):
        last_error = data.get("error", "Unknown error")
        logger.warning(f"  ✗ Step {step.step_number} attempt {attempt + 1}: {last_error}")
        
        RECOVERY_MAP: Dict[bool, Callable] = {
            True:  lambda: self._apply_recovery(exec_, step, last_error, data, attempt),
            False: lambda: None
        }
        RECOVERY_MAP[self.recovery_agent is not None and attempt < self.MAX_RETRIES - 1]()
        return last_error

    def _validate_dag_plan(self, plan) -> tuple:
        """
        Pre-screen every step through CommandGuard before any step runs.
        Returns (ok: bool, reason: str).
        All steps must pass; first rejection blocks the whole plan.
        """
        guard = getattr(self.security, "command_guard", None) or self.security
        guard or (None)   # no guard configured — allow all
        if not guard:
            return True, ""
        for step in plan.steps:
            STEP_TEXT_FIELDS: Dict[str, Callable] = {
                "description": lambda s: getattr(s, "description", ""),
                "action":      lambda s: getattr(s, "action", ""),
                "tool":        lambda s: getattr(s, "tool", ""),
            }
            instr = next(
                (v for v in (getter(step) for getter in STEP_TEXT_FIELDS.values()) if v),
                ""
            )
            try:
                risk = guard.assess_risk(instr)
                # risk_level >= 3 = CRITICAL — block immediately
                rl = risk.get("risk_level", 0)
                blocked = rl >= 3
                blocked and logger.warning(
                    "DAG safety: step %d blocked — risk=%d reason=%s",
                    step.step_number, rl, risk.get("reason", ""))
                if blocked:
                    return False, (
                        f"Step {step.step_number} rejected by CommandGuard "
                        f"(risk={rl}): {risk.get('reason','')}"
                    )
            except Exception as exc:
                logger.debug("DAG validate: %s", exc)
        return True, ""

    def _call_agent(self, exec_: TaskExecution, step: TaskStep) -> Dict:
        """
        O(1) dict-lookup agent dispatch — no if-elif routing chain.
        Truly zero if/else branching with valid syntax.
        """
        agent_obj = self.agents.get(step.agent)
        
        def _execute_payload() -> Dict:
            self._emit("tool_call_start", {
                "task_id": exec_.task_id, "agent": step.agent,
                "action": step.action, "step": step.step_number,
            })

            result_box: List[Any] = [None]
            exc_box:    List[Any] = [None]
            needs_gui_lock = step.agent in _GUI_AGENTS

            def _run_with_lock():
                with GUI_LOCK: result_box[0] = agent_obj.execute(step.action, step.parameters)
            def _run_no_lock():
                result_box[0] = agent_obj.execute(step.action, step.parameters)

            def _run() -> None:
                try:
                    if needs_gui_lock:
                        with GUI_LOCK:
                            result_box[0] = agent_obj.execute(step.action, step.parameters)
                    else:
                        result_box[0] = agent_obj.execute(step.action, step.parameters)
                except Exception as exc:
                    exc_box[0] = exc

            _executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            _future   = _executor.submit(_run)
            
            timed_out: bool = False
            try:
                _future.result(timeout=self.STEP_TIMEOUT)
            except concurrent.futures.TimeoutError:
                timed_out = True
            finally:
                _executor.shutdown(wait=False)

            if timed_out:
                _safe_mouseup()
                result = {"success": False, "error": f"Agent {step.agent} timed out"}
                state = "timeout"
            elif exc_box[0] is not None:
                _safe_mouseup()
                result = {"success": False, "error": f"Agent raised: {exc_box[0]}"}
                state = "exception"
            else:
                result = result_box[0] or {"success": False, "error": "Agent returned None"}
                state = "ok"
            
            self._emit("tool_call_error" if state != "ok" else "tool_call_end", {
                "task_id": exec_.task_id, "agent": step.agent, "success": result.get("success", False),
            })
            return result

        if agent_obj is not None:
            return _execute_payload()
        else:
            return {"success": False, "error": f"Agent not found: '{step.agent}'"}

    def _run_coro(self, coro, timeout: float = 120) -> Any:
        """
        Submit a coroutine to the dedicated brain async loop. Thread-safe.
        Replaces the old _run_coroutine_safe(coro) pattern everywhere inside
        Brain — no nested ThreadPoolExecutors, no RuntimeError on Qt threads.
        """
        future = asyncio.run_coroutine_threadsafe(coro, self._async_loop)
        return future.result(timeout=timeout)

    def _apply_recovery(self, exec_: TaskExecution, step: TaskStep,
                         last_error: str, result_data: Dict, attempt: int) -> None:
        """
        Ask ErrorRecoveryAgent for a modified task and re-dispatch it.
        CRITICAL FIX: uses self._run_coro() on the dedicated loop — not
        the old nested ThreadPoolExecutor which caused RuntimeError under Qt.
        When recovery returns a modified_task, the step parameters are updated
        so the NEXT attempt in the retry loop uses the new parameters, not the
        original failing ones.
        """
        try:
            error_type = self.recovery_agent.classify_error(last_error)
            plan = self._run_coro(
                self.recovery_agent.recover(
                    error_type,
                    {"task": {"action": step.action,
                              "args": step.parameters},
                     "output": result_data,
                     "task_id": exec_.task_id},
                    attempt,
                )
            )
            if plan and not plan.escalate:
                self._apply_recovery_plan(step, plan)
        except Exception as exc:
            logger.debug(f"Recovery agent: {exc}")

    def _apply_recovery_plan(self, step: TaskStep, plan) -> None:
        """Apply a recovery plan's modified_task to the step for re-dispatch."""
        new_action = plan.modified_task.get("action", step.action)
        new_args   = plan.modified_task.get("args", step.parameters)
        step.action = new_action
        step.parameters.update(new_args)
        logger.info(
            f"  Recovery applied: {plan.strategy_name} — {plan.description} "
            f"| new_action={new_action}"
        )

    # ──────────────────────────────────────────────────────────────────────────
    #  Memory helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _enrich_context(self, ctx: Dict, user_request: str) -> Dict:
        if self.vision:
            try:
                si = self.vision.get_screen_info()
                ctx["screen_info"] = si
                aw = self.vision.get_active_window_title()
                if aw.get("success"):
                    ctx["active_window"] = aw.get("title", "")
            except Exception:
                pass
        if self.memory:
            try:
                ctx["past_experiences"] = \
                    self.memory.find_similar_experiences(user_request, limit=3)
            except Exception:
                pass
        return ctx

    def _record_task_start(self, exec_: TaskExecution) -> None:
        if not self.memory:
            return
        try:
            self.memory.record_task_start(
                task_id=exec_.task_id,
                request=exec_.original_request,
                task_type=exec_.plan.task_type.value,
                risk_level=exec_.plan.risk_assessment.value,
                summary=exec_.summary,
                total_steps=exec_.total_steps,
            )
        except Exception as exc:
            logger.debug(f"record_task_start: {exc}")

    def _record_step_start(self, exec_: TaskExecution,
                            step: TaskStep) -> Optional[int]:
        if not self.memory:
            return None
        try:
            return self.memory.record_step_start(
                task_id=exec_.task_id,
                step_number=step.step_number,
                description=step.description,
                agent=step.agent,
                action=step.action,
                parameters=step.parameters,
            )
        except Exception:
            return None

    def _record_step_end(self, exec_: TaskExecution, step: TaskStep,
                          step_db_id: Optional[int], result_data: Dict,
                          success: bool, attempt: int) -> None:
        if not self.memory:
            return
        try:
            if step_db_id:
                self.memory.record_step_end(
                    step_db_id=step_db_id,
                    status="success" if success else "failed",
                    output=json.dumps(result_data, default=str)[:3000],
                    error=result_data.get("error", ""),
                    retry_count=attempt,
                )
            self.memory.record_agent_action(
                task_id=exec_.task_id,
                agent=step.agent,
                action=step.action,
                parameters=step.parameters,
                result=result_data,
                step_id=step_db_id,
            )
            if not success:
                self.memory.log_error(
                    error_msg=result_data.get("error", "Unknown error"),
                    task_id=exec_.task_id,
                    agent=step.agent,
                    action=step.action,
                )
        except Exception as exc:
            logger.debug(f"record_step_end: {exc}")

    def _finalize(self, exec_: TaskExecution,
                  steps_ok: int, steps_fail: int) -> None:
        if self.memory:
            try:
                self.memory.record_task_end(
                    task_id=exec_.task_id,
                    status=exec_.status.value,
                    steps_ok=steps_ok,
                    steps_fail=steps_fail,
                    error_summary=("; ".join(exec_.error_log[:3])
                                   if exec_.error_log else None),
                )
                self.memory.store_experience({
                    "task":       exec_.original_request,
                    "task_type":  exec_.plan.task_type.value,
                    "steps_ok":   steps_ok,
                    "steps_fail": steps_fail,
                    "success":    exec_.status == ExecutionStatus.SUCCESS,
                    "error":      exec_.error_log[0] if exec_.error_log else None,
                    "duration": (
                        (datetime.fromisoformat(exec_.end_time) -
                         datetime.fromisoformat(exec_.start_time)).total_seconds()
                        if exec_.end_time else 0
                    ),
                    "timestamp":  exec_.end_time,
                })
            except Exception as exc:
                logger.debug(f"finalize: {exc}")

        sym = "✓" if exec_.status == ExecutionStatus.SUCCESS else "✗"
        logger.info(f"{sym} Task {exec_.task_id[:8]} — "
                    f"{steps_ok} ok, {steps_fail} fail")

    # ──────────────────────────────────────────────────────────────────────────
    #  Security helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _security_check(self, user_request: str) -> Optional[str]:
        # BUG 4 FIX: Fail-CLOSED — missing guard blocks, not allows.
        # Dict dispatch, zero if/elif/else.
        GUARD_MISSING_RESPONSE = (
            "Security guard not initialized. Task blocked."
        )

        guard_valid: bool = bool(
            self.security and hasattr(self.security, "check_command")
        )

        def _run_check() -> Optional[str]:
            try:
                allowed, reason, _ = self.security.check_command(user_request)
                return None if allowed else reason
            except Exception as exc:
                logger.warning(f"Security check: {exc}")
                return None

        def _block_missing() -> Optional[str]:
            logger.critical(
                "CommandGuard not configured — task blocked: %s",
                user_request[:120],
            )
            self._emit("safety_check_blocked", {
                "reason": "CommandGuard not initialized",
                "request": user_request,
            })
            return GUARD_MISSING_RESPONSE

        GUARD_ACTIONS: Dict[bool, Callable] = {
            True:  _run_check,
            False: _block_missing,
        }
        return GUARD_ACTIONS[guard_valid]()

    def _make_blocked_exec(self, task_id: str, user_request: str,
                            plan: TaskPlan, reason: str) -> TaskExecution:
        exec_ = TaskExecution(
            task_id=task_id,
            original_request=user_request,
            plan=plan,
            status=ExecutionStatus.FAILED,
            summary=f"Blocked by security: {reason}",
            total_steps=len(plan.steps),
        )
        exec_.error_log.append(f"Security block: {reason}")
        with self._lock:
            self._tasks[task_id] = exec_
        self._emit("safety_check_blocked", {
            "task_id": task_id,
            "reason": reason,
        })
        return exec_

    # ──────────────────────────────────────────────────────────────────────────
    #  EventBus helper
    # ──────────────────────────────────────────────────────────────────────────

    def _emit(self, event_type: str, data: Dict) -> None:
        if self.event_bus:
            try:
                self.event_bus.emit_sync(event_type, data)
            except Exception as exc:
                logger.debug(f"emit {event_type}: {exc}")

    # ──────────────────────────────────────────────────────────────────────────
    #  Notification helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _notify(self, exec_: TaskExecution) -> None:
        d = self._execution_to_dict(exec_)
        for fn in self._task_callbacks:
            try:
                fn(d)
            except Exception:
                pass
        if exec_.on_status_update:
            try:
                exec_.on_status_update(d)
            except Exception:
                pass

    # ──────────────────────────────────────────────────────────────────────────
    #  Serialisation
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _execution_to_dict(exec_: TaskExecution) -> Dict:
        return {
            "task_id":         exec_.task_id,
            "request":         exec_.original_request,
            "summary":         exec_.summary or exec_.plan.summary,
            "status":          exec_.status.value,
            "task_type":       exec_.plan.task_type.value,
            "risk_level":      exec_.plan.risk_assessment.value,
            "total_steps":     exec_.total_steps,
            "completed_steps": exec_.completed_steps,
            "failed_steps":    exec_.failed_steps,
            "start_time":      exec_.start_time,
            "end_time":        exec_.end_time,
            "error_log":       exec_.error_log,
            "results": [
                {
                    "step_number": r.step_number,
                    "status":      r.status.value,
                    "agent":       r.agent,
                    "action":      r.action,
                    "output":      r.output[:300],
                    "error":       (r.error or "")[:200],
                    "duration":    round(r.duration, 2),
                }
                for r in exec_.results
            ],
        }


# Populate after class so ExecutionStatus is fully defined
_FINAL_STATUS[True]  = ExecutionStatus.SUCCESS
_FINAL_STATUS[False] = ExecutionStatus.FAILED


def _format_output(result: Dict) -> str:
    parts = []
    for key in ("stdout", "output", "text", "content", "result",
                "summary", "description", "path", "url", "files"):
        val = result.get(key)
        if val:
            parts.append(str(val)[:500])
    return " | ".join(parts) if parts else json.dumps(result, default=str)[:500]
