"""
core/execution/intent_recovery.py

R1 crash recovery authority: WAL recovery -> orphaned intents -> filesystem
observation -> digest comparison -> RECONCILED (or honest FAILED).

This component never executes adapters and never re-performs effects. It reads
the canonical RecoveryJournal (the same execution-side WAL the dispatcher
writes), reconstructs each intent's canonical state machine, and reconciles
orphaned intents by OBSERVING the filesystem against the recovery contract
(path + intended-content digest) that the dispatcher journaled BEFORE the
effect was attempted.

State machine legality comes from the canonical LEGAL_TRANSITIONS table:
    RUNNING   -> ORPHANED   (worker/supervisor died before verification)
    ORPHANED  -> RECOVERING -> RECONCILED (digest matches) | FAILED (it does not)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core.contracts.runtime_events import ExecutionEvent, ExecutionState, VerificationEvent
from core.execution.intent_execution_state import (
    IntentExecutionState,
    IntentStateError,
    IntentStateMachine,
    LEGAL_TRANSITIONS,
)
from core.execution.side_effect_observation import observe_file
from core.execution.recovery_journal import RecoveryJournal
from core.replay.replay_coordinator import ReplayCoordinator

logger = logging.getLogger("IntentRecovery")


class RecoveryIntegrityError(RuntimeError):
    """The WAL lineage contains illegal transitions; recovery refuses to run."""


class IntentRecovery:
    """Reconciles intents whose execution outlived their supervisor."""

    def __init__(self, journal: RecoveryJournal, event_bus=None):
        self.journal = journal
        self._event_bus = event_bus
        self._replay = ReplayCoordinator(journal)

    # ── Public API ──────────────────────────────────────────────────────────

    def scan_orphaned(self) -> List[str]:
        """
        WAL recovery pass. Returns intent_ids pending reconciliation:
        - RUNNING   -> journaled ORPHANED here (kernel died before it could),
        - ORPHANED  -> already marked, awaiting reconcile.
        Pre-effect leftovers (QUEUED/DISPATCHED) are journaled ABORTED — they
        never reached the worker, so no side effect can exist.

        Raises RecoveryIntegrityError on any illegal lineage: recovery must
        never reconcile against a WAL it cannot reason about.
        """
        analysis = self._analyze()

        pending: List[str] = []
        for intent_id in sorted(analysis["intents"]):
            info = analysis["intents"][intent_id]
            last_state = info.get("state")
            machine = self._reconstruct(intent_id, info["history"])

            if last_state == IntentExecutionState.RUNNING.value:
                self._transition(
                    machine,
                    intent_id,
                    IntentExecutionState.ORPHANED,
                    {
                        "stage": "orphaned",
                        "reason": "recovered from kernel restart while executing",
                        "path": info.get("payload", {}).get("path"),
                        "content_sha256": info.get("payload", {}).get("content_sha256"),
                    },
                )
                self._emit(
                    ExecutionEvent(
                        intent_id=intent_id,
                        state=ExecutionState.INVALIDATED,
                        payload={"reason": "kernel restart while executing"},
                        error="kernel restart while executing",
                    )
                )
                pending.append(intent_id)
            elif last_state == IntentExecutionState.ORPHANED.value:
                pending.append(intent_id)
            elif last_state in (
                IntentExecutionState.QUEUED.value,
                IntentExecutionState.DISPATCHED.value,
            ):
                # Pre-effect window: durable record exists but no frame was
                # ever sent (RUNNING is journaled before dispatch). Abort.
                self._transition(
                    machine,
                    intent_id,
                    IntentExecutionState.ABORTED,
                    {"stage": "aborted", "reason": "kernel restarted before dispatch"},
                )
            # COMPLETED / FAILED / COMPENSATED / REJECTED / RECONCILED: terminal,
            # nothing to do. VERIFYING: recovery of that narrow window is a
            # later phase (see authority manifest deferred list).
        return pending

    def reconcile(self, intent_id: str) -> str:
        """
        ORPHANED intent reconciliation:
        observe the filesystem, compare against the pre-dispatch digest, then
        journal RECONCILED (match) or FAILED (mismatch / no recovery contract).

        Returns the final IntentExecutionState value.
        """
        analysis = self._analyze()
        info = analysis["intents"].get(intent_id)
        if info is None:
            raise KeyError(f"Intent {intent_id} has no WAL lineage to reconcile.")

        machine = self._reconstruct(intent_id, info["history"])
        last_state = info.get("state")

        if last_state == IntentExecutionState.RUNNING.value:
            # Same orphaning scan pass, applied lazily.
            self.scan_orphaned()
            machine = self._reconstruct(intent_id, self._history(intent_id))
        elif last_state not in (
            IntentExecutionState.ORPHANED.value,
        ):
            raise IntentStateError(
                f"Intent {intent_id} is in {last_state}; only ORPHANED intents "
                f"can be reconciled (run scan_orphaned() first)."
            )

        if machine.current() != IntentExecutionState.ORPHANED:
            raise IntentStateError(
                f"Intent {intent_id} reconstructed to {machine.current().value}; "
                f"expected ORPHANED before reconcile."
            )

        contract = info.get("payload", {}) or {}
        path = contract.get("path")
        expected_sha256 = contract.get("content_sha256")

        # ORPHANED -> RECOVERING (durability barrier before observation).
        self._transition(
            machine,
            intent_id,
            IntentExecutionState.RECOVERING,
            {"stage": "recovering", "path": path, "content_sha256": expected_sha256},
        )

        if not path or not expected_sha256:
            error = (
                "WAL recovery contract missing path/content_sha256; "
                "the intent's effect cannot be reconciled by observation."
            )
            self._emit(
                VerificationEvent(
                    intent_id=intent_id,
                    success=False,
                    metrics={"error": error},
                    divergence_detected=True,
                )
            )
            self._transition(
                machine, intent_id, IntentExecutionState.FAILED,
                {"stage": "reconcile", "error": error},
            )
            return IntentExecutionState.FAILED.value

        observed = observe_file(path)
        metrics: Dict[str, Any] = {
            "path": path,
            "expected_sha256": expected_sha256,
            "observed_sha256": observed.sha256,
            "exists": observed.exists,
        }
        matched = bool(observed.exists and observed.sha256 == expected_sha256)
        metrics["matched"] = matched

        self._emit(
            VerificationEvent(
                intent_id=intent_id,
                success=matched,
                metrics=dict(metrics),
                divergence_detected=not matched,
            )
        )

        if matched:
            self._transition(
                machine,
                intent_id,
                IntentExecutionState.RECONCILED,
                {"stage": "reconciled", **metrics},
            )
            logger.info(
                f"Intent {intent_id}: orphaned effect observed and digests match -> RECONCILED"
            )
            return IntentExecutionState.RECONCILED.value

        error = (
            f"Filesystem observation diverged: exists={observed.exists}, "
            f"observed={observed.sha256}, expected={expected_sha256}"
        )
        self._transition(
            machine, intent_id, IntentExecutionState.FAILED,
            {"stage": "reconcile", "error": error, **metrics},
        )
        logger.error(f"Intent {intent_id}: {error} -> FAILED")
        return IntentExecutionState.FAILED.value

    # ── Internals ───────────────────────────────────────────────────────────

    def _analyze(self) -> Dict[str, Any]:
        analysis = self._replay.analyze_lineage()
        divergences = analysis.get("divergences_detected", 0)
        if divergences:
            raise RecoveryIntegrityError(
                f"WAL lineage contains {divergences} illegal transition(s); "
                f"refusing to reconcile against an untrustworthy journal."
            )
        return analysis

    def _history(self, intent_id: str) -> List[Dict[str, Any]]:
        return self._analyze()["intents"][intent_id]["history"]

    @staticmethod
    def _reconstruct(intent_id: str, history: List[Dict[str, Any]]) -> IntentStateMachine:
        machine = IntentStateMachine(intent_id)
        for record in history:
            machine.transition(IntentExecutionState(record["state"]))
        return machine

    def _transition(
        self,
        machine: IntentStateMachine,
        intent_id: str,
        new_state: IntentExecutionState,
        wal_payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Legality check -> fsynced WAL record -> commit in-memory."""
        allowed = LEGAL_TRANSITIONS.get(machine.current(), frozenset())
        if new_state not in allowed:
            raise IntentStateError(
                f"Intent {intent_id}: illegal recovery transition "
                f"{machine.current().value} -> {new_state.value}"
            )
        self.journal.log_transition(intent_id, new_state, wal_payload or {})
        machine.transition(new_state)

    def _emit(self, event) -> None:
        if self._event_bus is None:
            from core.orchestration.event_bus import get_event_bus

            bus = get_event_bus()
        else:
            bus = self._event_bus
        bus.emit_sync(event)
