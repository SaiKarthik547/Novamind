"""
core/execution/intent_dispatcher.py

R1: Canonical execution dispatcher — the routing link between
KernelExecutionFacade and the real execution lanes.

Responsibilities (exactly and only):
- Lane selection: the worker lane (real process inside a Windows Job Object
  sandbox) versus the transitional in-process adapter lane.
- WAL-before-effect: every execution-relevant state transition is fsynced to
  the canonical RecoveryJournal BEFORE the external side effect is requested,
  and the WAL record written before dispatch carries the recovery contract
  (target path + intended-content digest).
- Independent post-execution observation: the kernel reads the bytes on disk
  itself and compares digests before any intent may reach COMPLETED.
- Runtime event emission (ExecutionEvent / VerificationEvent) through the
  canonical topology bus.

It deliberately does NOT:
- schedule (ExecutionScheduler owns ordering),
- validate policy beyond structure (IntentGovernanceLayer owns governance),
- own lifecycle state (LifecycleAuthority),
- implement adapters (adapters own their operations).

The worker lane requires a KernelSupervisor (worker authority). Capabilities
in WORKER_LANE_CAPABILITIES fail closed if no worker authority is configured —
a HIGH_AUTHORITY, permanent side effect never falls back to in-process
execution just because a dependency is missing.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from core.contracts.intent_contracts import IntentContractRegistry
from core.contracts.runtime_events import ExecutionEvent, ExecutionState, VerificationEvent
from core.execution.capability_registry import CAPABILITY_REGISTRY
from core.execution.execution_intent import ExecutionIntent
from core.runtime.capability_broker import Capability
from core.execution.intent_execution_state import (
    IntentExecutionState,
    IntentStateError,
    IntentStateMachine,
    LEGAL_TRANSITIONS,
    TERMINAL_STATES,
)
from core.execution.intent_result import IntentResult
from core.execution.execution_intent import IntentStatus
from core.execution.side_effect_observation import observe_file
from core.ipc.worker_protocol import FrameType, WorkerState

logger = logging.getLogger("IntentDispatcher")

# Capabilities that MUST execute inside a Job Object sandbox (worker lane).
# R1 scope: filesystem.write. Later phases may move additional HIGH_AUTHORITY
# capabilities here; membership is an authority decision, not a hint.
WORKER_LANE_CAPABILITIES = frozenset({"filesystem.write"})

DEFAULT_DISPATCH_TIMEOUT = 30.0
DEFAULT_WORKER_READY_TIMEOUT = 15.0

_WORKER_LIVENESS_POLL_S = 0.02

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WORKER_LANE_SCRIPTS: Dict[str, str] = {
    "filesystem.write": os.path.join(_REPO_ROOT, "workers", "filesystem_worker.py"),
}


class DispatchError(RuntimeError):
    """The dispatcher refused or could not complete a dispatch."""


class DispatchTimeout(DispatchError):
    """The execution lane did not answer within the intent's timeout."""


class WorkerDiedError(DispatchError):
    """The supervising worker process died while the intent was executing."""


@dataclass
class DispatchContext:
    """Per-dispatch state: intent, lane decision, and its state machine."""

    intent: ExecutionIntent
    capability: str
    lane: str  # "worker" | "in_process"
    expected_sha256: Optional[str]
    state: IntentStateMachine
    wal_fields: Dict[str, Any] = field(default_factory=dict)


class IntentDispatcher:
    """
    Executes validated intents through the canonical lanes and proves the
    outcome by independent observation before journaling COMPLETED.
    """

    def __init__(
        self,
        adapter_supervisor=None,
        kernel_supervisor=None,
        journal=None,
        governance=None,
        event_bus=None,
        worker_lane_capabilities: Optional[frozenset] = None,
        worker_lane_scripts: Optional[Dict[str, str]] = None,
    ):
        self._adapter_supervisor = adapter_supervisor
        self._kernel_supervisor = kernel_supervisor
        self._governance = governance
        self._event_bus = event_bus
        self._worker_lane_capabilities = (
            worker_lane_capabilities
            if worker_lane_capabilities is not None
            else WORKER_LANE_CAPABILITIES
        )
        self._worker_lane_scripts = (
            worker_lane_scripts if worker_lane_scripts is not None else _WORKER_LANE_SCRIPTS
        )

        # Durability authority. Lazy: constructing a dispatcher performs no
        # I/O; the journal materializes on first use.
        self._journal = journal
        self._journal_lock = threading.Lock()

        # Worker-lane state (single supervised worker per dispatcher).
        self._worker_lock = threading.Lock()
        self._supervisor = None

        # In-flight EXECUTE_RESULT correlation (correlation_id == intent_id).
        self._pending_lock = threading.Lock()
        self._pending: Dict[str, Dict[str, Any]] = {}

    # ── Durability / observability authorities ──────────────────────────────

    @property
    def journal(self):
        if self._journal is None:
            with self._journal_lock:
                if self._journal is None:
                    if self._kernel_supervisor is not None:
                        self._journal = self._kernel_supervisor.wal
                    else:
                        from core.execution.recovery_journal import RecoveryJournal

                        self._journal = RecoveryJournal.get_instance()
        return self._journal

    def _transition(
        self,
        ctx: DispatchContext,
        new_state: IntentExecutionState,
        wal_payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Legality check -> fsynced WAL record -> commit to the in-memory
        machine. If the WAL write fails the in-memory transition is NOT
        committed, so a committed transition always has a durable record.
        """
        allowed = LEGAL_TRANSITIONS.get(ctx.state.current(), frozenset())
        if new_state not in allowed:
            raise IntentStateError(
                f"Intent {ctx.intent.intent_id[:8]}: illegal transition "
                f"{ctx.state.current().value} -> {new_state.value}"
            )
        self.journal.log_transition(
            intent_id=ctx.intent.intent_id,
            state=new_state,
            payload=wal_payload or {},
        )
        ctx.state.transition(new_state)

    def _emit(self, event) -> None:
        """
        Publish a runtime event through the canonical topology (fsync before
        propagation). Failures propagate: event durability is part of the
        execution contract, not best-effort telemetry.
        """
        bus = self._event_bus if self._event_bus is not None else _default_event_bus()
        bus.emit_sync(event)

    # ── Public API ──────────────────────────────────────────────────────────

    def dispatch_sync(
        self, intent: ExecutionIntent, timeout: float = DEFAULT_DISPATCH_TIMEOUT
    ) -> IntentResult:
        """
        Canonical single-intent dispatch: validate -> durable prepare ->
        execute in the assigned lane -> independent observe/hash verification
        -> COMPLETED (or honest failure) in the WAL + runtime events.
        """
        try:
            ctx = self.prepare(intent)
        except (ValueError, PermissionError, NotImplementedError) as exc:
            # Rejected before any effect; prepare already journaled REJECTED.
            return IntentResult(
                intent_id=intent.intent_id,
                status=IntentStatus.FAILED,
                success=False,
                payload={},
                error=str(exc),
                metrics={"stage": "rejected", "capability": self._capability_of(intent)},
            )

        try:
            if ctx.lane == "worker":
                outcome = self.execute_in_worker(ctx, timeout=timeout)
            else:
                outcome = self.execute_in_process(ctx)
        except WorkerDiedError as exc:
            self.mark_orphaned(ctx, reason=str(exc))
            return IntentResult(
                intent_id=intent.intent_id,
                status=IntentStatus.FAILED,
                success=False,
                payload={},
                error=f"Intent orphaned: {exc}",
                metrics={"stage": "orphaned", "capability": ctx.capability},
            )
        except Exception as exc:
            self.mark_failed(ctx, stage="execution", error=str(exc))
            return IntentResult(
                intent_id=intent.intent_id,
                status=IntentStatus.FAILED,
                success=False,
                payload={},
                error=str(exc),
                metrics={"stage": "execution", "capability": ctx.capability},
            )

        try:
            return self.verify_and_complete(ctx, outcome)
        except Exception as exc:
            self.mark_failed(ctx, stage="verification", error=str(exc))
            return IntentResult(
                intent_id=intent.intent_id,
                status=IntentStatus.FAILED,
                success=False,
                payload={},
                error=f"Verification failed: {exc}",
                metrics={"stage": "verification", "capability": ctx.capability},
            )

    def prepare(self, intent: ExecutionIntent) -> DispatchContext:
        """
        Structural validation -> capability/authority resolution -> durable
        QUEUED/DISPATCHED/RUNNING records (recovery contract included) with
        NO external effect performed here.

        Raises after journaling REJECTED when validation or authority
        resolution refuses the intent.

        R2-A: Acquire a broker lease and bind it to the intent for the
        canonical execution path. The lease is included in the EXECUTE_REQUEST
        frame so the worker can validate at the boundary.
        """
        from core.runtime.capability_broker import CapabilityBroker
        broker = CapabilityBroker()

        capability = self._capability_of(intent)
        lane = "worker" if capability in self._worker_lane_capabilities else "in_process"

        try:
            # 1. Governance/contract structure (governance owns policy).
            if self._governance is not None:
                self._governance.validate_intent(intent)
            else:
                IntentContractRegistry.validate_intent(intent)

            # 2. Capability authority + lane feasibility. Fail closed.
            if lane == "worker":
                CAPABILITY_REGISTRY.require(capability)
                if self._kernel_supervisor is None:
                    raise PermissionError(
                        f"Capability '{capability}' must execute in the worker lane "
                        f"(Job Object sandbox), but no worker authority is configured. "
                        f"Failing closed — no in-process fallback for permanent effects."
                    )
                if capability not in self._worker_lane_scripts:
                    raise PermissionError(
                        f"Worker-lane capability '{capability}' has no registered worker "
                        f"script. Failing closed."
                    )
            else:
                if self._adapter_supervisor is None:
                    raise PermissionError(
                        f"No in-process adapter authority configured for '{capability}'. "
                        f"Failing closed."
                    )
        except (ValueError, PermissionError, NotImplementedError) as exc:
            self._journal_rejection(intent, capability, str(exc))
            raise

        # R2-A: Acquire a lease bound to this intent for worker boundary validation
        # For the canonical worker lane, a lease is mandatory.
        # For R1 legacy intents (in_process lane), lease_id remains None.
        lease_id = None
        lease_validation_data = None  # R2-A: data for worker-side validation
        if lane == "worker":
            # Bind lease to intent identity for the canonical path
            lease = broker.request_lease(
                task_id=f"dispatch-{intent.intent_id}",
                capabilities=[Capability.FILE_WRITE] if capability == "filesystem.write" else [],
                allowed_paths=[],
                intent_id=intent.intent_id,
                principal=getattr(intent, "principal", "UNKNOWN"),
                agent_id=getattr(intent, "agent_id", "UNKNOWN"),
            )
            lease_id = lease.lease_id
            # Store lease validation data in wal_fields so the worker can validate
            # the lease without needing shared broker state (R2-A integration fix)
            lease_validation_data = {
                "lease_intent_id": lease.intent_id,
                "lease_principal": lease.principal,
                "lease_agent_id": lease.agent_id,
                "lease_capabilities": [cap.value for cap in lease.capabilities],
                "lease_allowed_paths": lease.allowed_paths,
                "lease_allowed_path_target": intent.payload.get("path", ""),
                "lease_expiration": lease.expiration,
                "lease_revoked": lease.revoked,
                "lease_lifecycle_state": lease.lifecycle_state,
            }

        expected_sha256 = self._expected_digest(intent)
        ctx = DispatchContext(
            intent=intent,
            capability=capability,
            lane=lane,
            expected_sha256=expected_sha256,
            state=IntentStateMachine(intent.intent_id),
            wal_fields={
                "capability": capability,
                "lane": lane,
                "adapter": intent.adapter,
                "operation": intent.operation,
                "authority_origin": getattr(intent, "authority_origin", None),
                "path": intent.payload.get("path"),
                "content_sha256": expected_sha256,
                "idempotent": bool(intent.idempotent),
                "lease_id": lease_id,
                "lease_validation_data": lease_validation_data,
            },
        )

        # 3. Durable preparation (no effect yet).
        self._transition(ctx, IntentExecutionState.QUEUED, dict(ctx.wal_fields))
        self._transition(
            ctx,
            IntentExecutionState.DISPATCHED,
            {"capability": capability, "lane": lane},
        )
        self._emit(
            ExecutionEvent(
                intent_id=intent.intent_id,
                state=ExecutionState.DISPATCHED,
                payload={"capability": capability, "lane": lane},
            )
        )
        # 4. Durability barrier BEFORE the effect: RUNNING is journaled before
        #    any frame is sent, so a crash after this point always surfaces as
        #    an orphaned (possibly effected) intent, never as a lost one.
        self._transition(
            ctx,
            IntentExecutionState.RUNNING,
            {"path": ctx.wal_fields["path"], "content_sha256": expected_sha256},
        )
        return ctx

    def ensure_worker(self, timeout: float = DEFAULT_WORKER_READY_TIMEOUT) -> Tuple[str, Any]:
        """
        Provision (or restart) this dispatcher's supervised worker and wait
        until its handshake reports READY. Idempotent: a live worker is reused.
        """
        if self._kernel_supervisor is None:
            raise DispatchError(
                "Worker lane requested but no kernel supervisor (worker authority) configured."
            )

        with self._worker_lock:
            sup = self._supervisor
            if not _supervisor_alive(sup):
                script = self._worker_lane_scripts["filesystem.write"]
                worker_cmd = [sys.executable, script]
                worker_id = self._kernel_supervisor.launch_worker(worker_cmd)
                sup = self._kernel_supervisor.workers[worker_id]
                sup.on_message = self._on_worker_frame
                self._supervisor = sup
            worker_id = sup.identity.worker_id

        deadline = time.monotonic() + timeout
        while sup.state != WorkerState.READY:
            if not _supervisor_alive(sup):
                raise WorkerDiedError(
                    f"Worker {worker_id} died during boot "
                    f"(death_reason={sup.death_reason.value})."
                )
            if time.monotonic() >= deadline:
                raise DispatchError(
                    f"Worker {worker_id} did not reach READY within {timeout:.1f}s."
                )
            time.sleep(_WORKER_LIVENESS_POLL_S)
        return worker_id, sup

    def execute_in_worker(
        self, ctx: DispatchContext, timeout: float = DEFAULT_DISPATCH_TIMEOUT
    ) -> Dict[str, Any]:
        """
        Send EXECUTE_REQUEST to the supervised worker and wait for the
        correlated EXECUTE_RESULT, detecting worker death while waiting.
        """
        worker_id, sup = self.ensure_worker()
        intent_id = ctx.intent.intent_id

        entry = {"event": threading.Event(), "frame": None}
        with self._pending_lock:
            self._pending[intent_id] = entry
        try:
            # R2-A: Include lease_id and lease validation data in the EXECUTE_REQUEST
            # frame so the worker can validate the lease at the boundary without
            # needing shared broker state.
            intent_dict = ctx.intent.to_dict()
            # Propagate lease_id from wal_fields
            lease_id_from_wal = ctx.wal_fields.get("lease_id")
            if lease_id_from_wal is not None:
                intent_dict["lease_id"] = lease_id_from_wal
            # Propagate lease validation data from wal_fields so worker can validate
            # the lease without needing shared broker state.
            lease_validation_data_from_wal = ctx.wal_fields.get("lease_validation_data")
            if lease_validation_data_from_wal is not None:
                intent_dict.update(lease_validation_data_from_wal)
            sup.send_frame(
                FrameType.EXECUTE_REQUEST,
                {"intent": intent_dict},
                correlation_id=intent_id,
            )
            deadline = time.monotonic() + timeout
            while not entry["event"].wait(timeout=_WORKER_LIVENESS_POLL_S):
                if not _supervisor_alive(sup):
                    raise WorkerDiedError(
                        f"Worker {worker_id} died while intent {intent_id} was executing."
                    )
                if time.monotonic() >= deadline:
                    raise DispatchTimeout(
                        f"Worker {worker_id} did not answer intent {intent_id} "
                        f"within {timeout:.1f}s."
                    )

            frame = entry["frame"]
            if frame is None:
                raise DispatchError(f"No EXECUTE_RESULT correlated to intent {intent_id}.")
            payload = frame.payload or {}
            if not payload.get("success"):
                raise DispatchError(
                    f"Worker execution failed for {intent_id}: "
                    f"{payload.get('error', 'unknown worker error')}"
                )
            reported = payload.get("result")
            return {
                "lane": "worker",
                "worker_id": worker_id,
                "worker_pid": getattr(sup.process, "pid", None),
                "worker_reported": reported if isinstance(reported, dict) else {},
            }
        finally:
            with self._pending_lock:
                self._pending.pop(intent_id, None)

    def execute_in_process(self, ctx: DispatchContext) -> Dict[str, Any]:
        """Transitional in-process adapter lane (no OS sandbox boundary)."""
        if self._adapter_supervisor is None:
            raise DispatchError("No in-process adapter authority configured.")
        result = self._adapter_supervisor.execute_intent(ctx.intent)
        ok, error = _adapter_result_ok(result)
        if not ok:
            raise DispatchError(error)
        return {
            "lane": "in_process",
            "worker_id": None,
            "worker_pid": None,
            "worker_reported": result if isinstance(result, dict) else {"result": result},
        }

    def verify_and_complete(self, ctx: DispatchContext, outcome: Dict[str, Any]) -> IntentResult:
        """
        VERIFYING in the WAL -> runtime events -> independent observation and
        digest comparison -> COMPLETED only if the bytes on disk match the
        intended content recorded before dispatch.
        """
        intent_id = ctx.intent.intent_id
        worker_reported = outcome.get("worker_reported") or {}

        self._transition(
            ctx,
            IntentExecutionState.VERIFYING,
            {"stage": "verify", "lane": ctx.lane, "worker_id": outcome.get("worker_id")},
        )
        self._emit(
            ExecutionEvent(
                intent_id=intent_id,
                state=ExecutionState.MUTATED,
                payload={"lane": ctx.lane, "worker_id": outcome.get("worker_id")},
            )
        )

        metrics: Dict[str, Any] = {
            "lane": ctx.lane,
            "capability": ctx.capability,
            "content_sha256": ctx.expected_sha256,
        }
        if outcome.get("worker_id"):
            metrics["worker_id"] = outcome["worker_id"]
        if outcome.get("worker_pid"):
            metrics["worker_pid"] = outcome["worker_pid"]
        if isinstance(worker_reported, dict) and worker_reported.get("sha256"):
            metrics["worker_reported_sha256"] = worker_reported["sha256"]

        payload: Dict[str, Any] = dict(worker_reported) if isinstance(worker_reported, dict) else {}

        if ctx.expected_sha256:
            # Kernel-side observation: read the authoritative bytes directly.
            path = ctx.intent.payload.get("path")
            observed = observe_file(path)
            metrics["observed_sha256"] = observed.sha256
            payload["observed_sha256"] = observed.sha256
            payload["path"] = path
            self._emit(
                ExecutionEvent(
                    intent_id=intent_id,
                    state=ExecutionState.OBSERVED,
                    payload={"path": path, "exists": observed.exists, "sha256": observed.sha256},
                )
            )

            problems = []
            if not observed.exists:
                problems.append(f"target file missing after dispatch: {path}")
            elif observed.sha256 != ctx.expected_sha256:
                problems.append(
                    f"on-disk digest {observed.sha256} != intended digest {ctx.expected_sha256}"
                )
            reported_digest = (
                worker_reported.get("sha256") if isinstance(worker_reported, dict) else None
            )
            if reported_digest and reported_digest != ctx.expected_sha256:
                problems.append(
                    f"worker-reported digest {reported_digest} != intended digest "
                    f"{ctx.expected_sha256}"
                )

            if problems:
                error = "; ".join(problems)
                metrics["divergence"] = error
                self._emit(
                    VerificationEvent(
                        intent_id=intent_id,
                        success=False,
                        metrics=dict(metrics),
                        divergence_detected=True,
                    )
                )
                self._transition(
                    ctx, IntentExecutionState.FAILED, {"stage": "verification", "error": error}
                )
                return IntentResult(
                    intent_id=intent_id,
                    status=IntentStatus.FAILED,
                    success=False,
                    payload=payload,
                    error=error,
                    metrics=metrics,
                )

            self._emit(
                ExecutionEvent(
                    intent_id=intent_id,
                    state=ExecutionState.VERIFIED,
                    payload={"sha256": ctx.expected_sha256},
                )
            )

        # Terminal: event evidence first, then the durable COMPLETED record.
        self._emit(
            VerificationEvent(intent_id=intent_id, success=True, metrics=dict(metrics))
        )
        self._transition(
            ctx,
            IntentExecutionState.COMPLETED,
            {
                "stage": "completed",
                "observed_sha256": metrics.get("observed_sha256"),
                "content_sha256": ctx.expected_sha256,
                "verified": True,
            },
        )
        return IntentResult(
            intent_id=intent_id,
            status=IntentStatus.COMPLETED,
            success=True,
            payload=payload,
            metrics=metrics,
        )

    def mark_orphaned(self, ctx: DispatchContext, reason: str) -> None:
        """
        Record that the intent was executing when its worker died and its
        effect is UNVERIFIED (RUNNING -> ORPHANED). Reconciliation against the
        filesystem is IntentRecovery's job, not this dispatcher's.
        """
        if ctx.state.current() != IntentExecutionState.RUNNING:
            raise IntentStateError(
                f"Cannot orphan intent {ctx.intent.intent_id[:8]} from "
                f"{ctx.state.current().value} (only RUNNING can be orphaned)."
            )
        self._transition(
            ctx,
            IntentExecutionState.ORPHANED,
            {
                "stage": "orphaned",
                "reason": reason,
                "path": ctx.wal_fields.get("path"),
                "content_sha256": ctx.wal_fields.get("content_sha256"),
            },
        )
        self._emit(
            ExecutionEvent(
                intent_id=ctx.intent.intent_id,
                state=ExecutionState.INVALIDATED,
                payload={"reason": reason},
                error=reason,
            )
        )

    def mark_failed(self, ctx: DispatchContext, stage: str, error: str) -> None:
        """
        Honest failure from any non-terminal state:
        - QUEUED means nothing was dispatched yet -> ABORTED (no effect).
        - DISPATCHED/RUNNING/VERIFYING -> FAILED.
        Terminal states are left untouched (idempotent).
        """
        current = ctx.state.current()
        if current in TERMINAL_STATES:
            logger.warning(
                f"Intent {ctx.intent.intent_id[:8]} already terminal ({current.value}); "
                f"not recording failure from stage {stage}."
            )
            return
        if current == IntentExecutionState.QUEUED:
            target = IntentExecutionState.ABORTED
        else:
            target = IntentExecutionState.FAILED
        self._transition(ctx, target, {"stage": stage, "error": error})
        self._emit(
            VerificationEvent(
                intent_id=ctx.intent.intent_id,
                success=False,
                metrics={"stage": stage, "error": error},
                divergence_detected=True,
            )
        )

    # ── Internals ───────────────────────────────────────────────────────────

    @staticmethod
    def _capability_of(intent: ExecutionIntent) -> str:
        return f"{intent.adapter}.{intent.operation}"

    @staticmethod
    def _expected_digest(intent: ExecutionIntent) -> Optional[str]:
        """Digest of the intended content, recorded in the WAL pre-dispatch."""
        if intent.operation != "write":
            return None
        content = intent.payload.get("content")
        if not isinstance(content, str):
            return None
        encoding = intent.payload.get("encoding", "utf-8")
        return hashlib.sha256(content.encode(encoding)).hexdigest()

    def _journal_rejection(self, intent: ExecutionIntent, capability: str, error: str) -> None:
        """Durably record that the intent was REJECTED before any effect."""
        try:
            ctx = DispatchContext(
                intent=intent,
                capability=capability,
                lane="none",
                expected_sha256=None,
                state=IntentStateMachine(intent.intent_id),
            )
            self._transition(
                ctx,
                IntentExecutionState.REJECTED,
                {"stage": "rejected", "error": error, "capability": capability},
            )
        except Exception:
            # If even the rejection cannot be journaled (e.g. disk failure),
            # surface the original refusal to the caller below.
            logger.error(
                f"Failed to journal REJECTED for intent {intent.intent_id}: "
                f"rejection record could not be written",
                exc_info=True,
            )

    def _on_worker_frame(self, frame) -> None:
        """Supervisor IO-thread callback: correlate EXECUTE_RESULT frames."""
        if frame.type != FrameType.EXECUTE_RESULT:
            return
        with self._pending_lock:
            entry = self._pending.get(frame.correlation_id)
            if entry is None:
                return  # late result for an already-abandoned intent
            entry["frame"] = frame
        entry["event"].set()


def _supervisor_alive(sup) -> bool:
    if sup is None:
        return False
    if sup.state in (WorkerState.DEAD, WorkerState.TERMINATING):
        return False
    if sup.process is None:
        return False
    return sup.process.poll() is None


def _adapter_result_ok(result) -> tuple:
    """Transitional rule for in-process adapter results (see module docstring)."""
    if result is None:
        return False, "adapter returned no result"
    if isinstance(result, dict):
        if result.get("success") is False:
            return False, result.get("error") or "adapter reported failure"
        if "error" in result:
            return False, str(result["error"])
    return True, None


def _default_event_bus():
    from core.orchestration.event_bus import get_event_bus

    return get_event_bus()
