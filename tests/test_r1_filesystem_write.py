"""
tests/test_r1_filesystem_write.py

R1 — Recoverable Filesystem Execution: the first controlled vertical slice.

Proves the canonical chain end-to-end, with real external effects:

  Happy path:
    ExecutionIntent
      -> CapabilityRegistry resolve filesystem.write
      -> IntentGovernanceLayer validation
      -> ExecutionScheduler -> KernelExecutionFacade -> IntentDispatcher
      -> real worker process inside a Windows Job Object
      -> real FilesystemAdapter (atomic temp+fsync+os.replace write)
      -> kernel-side observation + sha256 comparison
      -> canonical WAL entry (QUEUED..COMPLETED, fsync barriers)
      -> runtime events (ExecutionEvent/VerificationEvent, journal-fsynced)
      -> runtime lifecycle still READY

  Crash path:
    worker killed AFTER the write committed but BEFORE verification
      -> intent marked ORPHANED (RUNNING -> ORPHANED, WAL)
      -> worker restarted
      -> WAL recovery (ReplayCoordinator lineage, 0 divergences)
      -> filesystem observation -> hash comparison -> RECONCILED

All filesystem mutation targets live in per-test temp directories. The test
never trusts the runtime's own digest reporting alone: expected digests are
computed here with hashlib, and on-disk bytes are re-read independently.
"""

import hashlib
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from core.adapters.adapter_supervisor import AdapterSupervisor
from core.contracts.runtime_events import ExecutionEvent, ExecutionState, VerificationEvent
from core.execution.capability_registry import CAPABILITY_REGISTRY, DeterminismClass, ReplayPolicy
from core.execution.execution_intent import ExecutionIntent, IntentStatus, RollbackMode, VerificationMode
from core.execution.execution_scheduler import ExecutionScheduler
from core.execution.intent_dispatcher import IntentDispatcher
from core.execution.intent_governance import IntentGovernanceLayer
from core.execution.intent_recovery import IntentRecovery
from core.execution.kernel_facade import KernelExecutionFacade
from core.execution.recovery_journal import RecoveryJournal
from core.orchestration.event_bus import get_event_bus
from core.replay.replay_coordinator import ReplayCoordinator
from core.runtime.kernel_supervisor import KernelSupervisor
from core.runtime.lifecycle_authority import RuntimeLifecycleState

DISPATCH_TIMEOUT = 30.0
FUTURE_TIMEOUT = 30.0


def _digest(data: bytes) -> str:
    """The test's OWN digest computation — never the runtime's."""
    return hashlib.sha256(data).hexdigest()


def _wait_for(predicate, timeout: float = 10.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class R1TestBase(unittest.TestCase):
    """Shared wiring: temp workspace, canonical journal, dispatcher, scheduler."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="r1_fs_write_")
        self.wal_path = os.path.join(self.tmp, "r1_intent.wal")

        self.ks = KernelSupervisor(wal_path=os.path.join(self.tmp, "r1_ks.wal"))
        self.adapter_supervisor = AdapterSupervisor(self.ks)
        self.governance = IntentGovernanceLayer()
        self.journal = RecoveryJournal(self.wal_path)
        self.dispatcher = IntentDispatcher(
            adapter_supervisor=self.adapter_supervisor,
            kernel_supervisor=self.ks,
            journal=self.journal,
            governance=self.governance,
        )
        self.facade = KernelExecutionFacade(dispatcher=self.dispatcher)
        self.scheduler = ExecutionScheduler(kernel_facade=self.facade)
        self.scheduler.start()

        self.bus = get_event_bus()
        self.bus.clear_log()

    def tearDown(self):
        self.scheduler.stop()
        for worker in list(self.ks.workers.values()):
            try:
                worker.stop()
            except Exception:
                pass
        try:
            self.journal.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    # Helpers -----------------------------------------------------------------

    def make_intent(self, intent_id: str, content: str, filename: str = "proof.txt"):
        target = os.path.join(self.tmp, filename)
        expected = _digest(content.encode("utf-8"))
        intent = ExecutionIntent(
            adapter="filesystem",
            operation="write",
            idempotent=False,  # matches the canonical filesystem.write contract
            verification_mode=VerificationMode.EXACT,
            rollback_strategy=RollbackMode.NO_ROLLBACK,
            capability_scope={"capability": "filesystem.write"},
            payload={"path": target, "content": content},
            intent_id=intent_id,
            authority_origin="kernel",
        )
        # R2-A: Add lease validation data for canonical path authorization
        lease_validation_data = {
            "lease_intent_id": intent.intent_id,
            "lease_principal": getattr(intent, "principal", "UNKNOWN"),
            "lease_agent_id": getattr(intent, "agent_id", "UNKNOWN"),
            "lease_capabilities": ["FILE_WRITE"],
            "lease_allowed_paths": [os.path.dirname(target)],
            "lease_expiration": 2000000000000.0,  # Far future
            "lease_revoked": False,
            "lease_lifecycle_state": "ACTIVE",
        }
        return intent, target, expected, lease_validation_data

    def wal_states(self, intent_id: str):
        with open(self.wal_path, "r", encoding="utf-8") as f:
            records = [json.loads(line) for line in f if line.strip()]
        return [
            r["state"] for r in records if r.get("intent_id") == intent_id
        ], [r for r in records if r.get("intent_id") == intent_id]

    def events_for(self, intent_id: str):
        return [
            e
            for e in self.bus._event_log
            if getattr(e, "intent_id", None) == intent_id
        ]

    def intent_events_in_topology_journal(self, intent_id: str) -> int:
        """Count durably-fsynced topology journal lines carrying this intent."""
        root = Path("runtime/logs")
        if not root.exists():
            return 0
        hits = 0
        for journal_file in root.glob("session_*/*.jsonl"):
            try:
                with open(journal_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if intent_id in line:
                            hits += 1
            except OSError:
                continue
        return hits


class TestR1FullChain(R1TestBase):
    """capability -> governance -> facade/scheduler -> worker -> verify -> WAL -> event -> READY"""

    def test_capability_resolves_with_r1_policies(self):
        defn = CAPABILITY_REGISTRY.require("filesystem.write")
        self.assertEqual(defn.determinism_class, DeterminismClass.DETERMINISTIC)
        self.assertEqual(defn.replay_policy, ReplayPolicy.STRUCTURAL)
        self.assertTrue(defn.side_effect_permanent)
        self.assertEqual(defn.verification_mode, "SIDE_EFFECT_VERIFICATION")

    def test_governance_rejects_malformed_intent_without_mutation(self):
        target = os.path.join(self.tmp, "never.txt")
        bad_intent = ExecutionIntent(
            adapter="filesystem",
            operation="write",
            idempotent=False,
            verification_mode=VerificationMode.EXACT,
            rollback_strategy=RollbackMode.NO_ROLLBACK,
            capability_scope={"capability": "filesystem.write"},
            payload={"path": target},  # 'content' missing
            intent_id="r1-reject-0001",
            authority_origin="kernel",
        )
        with self.assertRaises(ValueError):
            self.governance.validate_intent(bad_intent)

        # Dispatching it must fail closed: REJECTED journaled, no effect, no
        # worker ever spawned.
        result = self.dispatcher.dispatch_sync(bad_intent, timeout=DISPATCH_TIMEOUT)
        self.assertFalse(result.success)
        self.assertIn("content", result.error or "")
        self.assertEqual(result.metrics.get("stage"), "rejected")
        self.assertFalse(os.path.exists(target))
        self.assertEqual(len(self.ks.workers), 0)

        states, records = self.wal_states("r1-reject-0001")
        self.assertEqual(states, ["REJECTED"])
        self.assertIn("content", json.dumps(records[0]["payload"]))

    def test_full_chain_write_completes_with_verified_effects(self):
        # 0. Boot the canonical runtime; lifecycle must start READY.
        from core.runtime.runtime_bootstrap import RuntimeBootstrap

        rb = RuntimeBootstrap()
        self.assertEqual(rb.lifecycle_authority.get_state(), RuntimeLifecycleState.READY)

        content = "R1 vertical slice: recoverable filesystem execution " * 4
        intent, target, expected, _ = self.make_intent("r1-full-0001", content)

        # Baseline: topology journal lines already carrying this intent id
        # (from a previous run of this suite) must not satisfy the later
        # durability assertion — only NEW lines count.
        journal_hits_before = self.intent_events_in_topology_journal(
            intent.intent_id
        )

        # 1. Capability authority resolves.
        defn = CAPABILITY_REGISTRY.require("filesystem.write")
        self.assertIsNotNone(defn)

        # 2. Governance validates the constructed intent.
        self.governance.validate_intent(intent)

        # 3+4. Scheduler -> facade -> dispatcher -> real worker lane.
        future = self.scheduler.submit_intent(
            capability="filesystem.write",
            payload=dict(intent.payload),
            intent_meta={"intent_id": intent.intent_id, "idempotent": False},
            timeout=DISPATCH_TIMEOUT,
        )
        result = future.wait(timeout=FUTURE_TIMEOUT)

        # 5. Canonical result.
        self.assertIsNotNone(result, "scheduler future never resolved")
        self.assertTrue(result.success, getattr(result, "error", None))
        self.assertEqual(result.status, IntentStatus.COMPLETED)
        self.assertEqual(result.metrics.get("lane"), "worker")

        # 6. Independent observation: bytes on disk match, digest matches the
        #    test's own computation, no temp artifacts remain.
        with open(target, "rb") as f:
            on_disk = f.read()
        self.assertEqual(on_disk, content.encode("utf-8"))
        self.assertEqual(_digest(on_disk), expected)
        self.assertEqual(result.metrics.get("content_sha256"), expected)
        self.assertEqual(result.metrics.get("observed_sha256"), expected)
        self.assertEqual(result.metrics.get("worker_reported_sha256"), expected)
        leftovers = [
            name for name in os.listdir(os.path.dirname(target))
            if name.endswith(".tmp")
        ]
        self.assertEqual(leftovers, [], "atomic write must leave no temp files")

        # 7. Real worker evidence: sandboxed process, Job Object, and the
        #    kernel-side in-process adapter lane was NOT used for the effect.
        worker_id = result.metrics["worker_id"]
        supervisor = self.ks.workers[worker_id]
        self.assertIsNotNone(supervisor.sandbox._job_handle, "Job Object missing")
        self.assertIsNotNone(supervisor.process)
        self.assertIsNone(supervisor.process.poll(), "worker must still be alive")
        self.assertEqual(len(self.adapter_supervisor._active_adapters), 0)

        # 8. Canonical WAL: full chain with the recovery contract recorded
        #    BEFORE the effect, and an intact lineage (0 divergences).
        states, records = self.wal_states(intent.intent_id)
        self.assertEqual(
            states, ["QUEUED", "DISPATCHED", "RUNNING", "VERIFYING", "COMPLETED"]
        )
        queued = records[0]["payload"]
        self.assertEqual(queued["capability"], "filesystem.write")
        self.assertEqual(queued["lane"], "worker")
        self.assertEqual(queued["path"], target)
        self.assertEqual(queued["content_sha256"], expected)
        completed = records[-1]["payload"]
        self.assertTrue(completed.get("verified"))
        self.assertEqual(completed.get("observed_sha256"), expected)

        analysis = ReplayCoordinator(self.journal).analyze_lineage()
        self.assertEqual(analysis["divergences_detected"], 0)
        self.assertEqual(analysis["reconstructed_intents"], 1)

        # 9. Runtime events, in-memory AND durably journal-fsynced.
        events = self.events_for(intent.intent_id)
        execution_states = [
            e.state for e in events if isinstance(e, ExecutionEvent)
        ]
        for expected_state in (
            ExecutionState.DISPATCHED,
            ExecutionState.MUTATED,
            ExecutionState.OBSERVED,
            ExecutionState.VERIFIED,
        ):
            self.assertIn(expected_state, execution_states)
        verifications = [e for e in events if isinstance(e, VerificationEvent)]
        self.assertTrue(verifications)
        self.assertTrue(verifications[-1].success)
        self.assertGreater(
            self.intent_events_in_topology_journal(intent.intent_id),
            journal_hits_before,
            "runtime events must be durably journaled, not just published",
        )

        # 10. Lifecycle stays READY across execution.
        self.assertEqual(
            rb.lifecycle_authority.get_state(), RuntimeLifecycleState.READY
        )


class TestR1CrashRecovery(R1TestBase):
    """kill worker before verification -> restart -> WAL recovery -> RECONCILED"""

    def test_worker_killed_before_verification_reconciles(self):
        content = "crash-window payload: write committed, verification never ran"
        intent, target, expected, _ = self.make_intent(
            "r1-crash-0001", content, filename="crash_proof.txt"
        )

        # Phase 1 — durable prepare + REAL worker execution (write commits).
        ctx = self.dispatcher.prepare(intent)
        outcome = self.dispatcher.execute_in_worker(ctx, timeout=DISPATCH_TIMEOUT)
        with open(target, "rb") as f:
            self.assertEqual(f.read(), content.encode("utf-8"))

        # Phase 2 — hard-kill the worker BEFORE any verification runs.
        supervisor = self.ks.workers[outcome["worker_id"]]
        supervisor.process.kill()
        supervisor.process.wait(timeout=5)
        self.assertTrue(
            _wait_for(lambda: supervisor.state.value == "DEAD", timeout=5),
            f"worker did not reach DEAD (state={supervisor.state})",
        )

        # The production path on worker death: RUNNING -> ORPHANED (WAL).
        self.dispatcher.mark_orphaned(
            ctx, reason="worker killed before verification"
        )
        states, _ = self.wal_states(intent.intent_id)
        self.assertEqual(states, ["QUEUED", "DISPATCHED", "RUNNING", "ORPHANED"])
        # Verification must NOT have run: no VERIFYING/COMPLETED record.
        self.assertNotIn("VERIFYING", states)
        self.assertNotIn("COMPLETED", states)

        # Phase 3 — restart: a replacement worker provisions and handshakes.
        new_worker_id, new_supervisor = self.dispatcher.ensure_worker()
        self.assertNotEqual(new_worker_id, outcome["worker_id"])
        self.assertEqual(new_supervisor.state.value, "READY")
        self.assertIsNone(new_supervisor.process.poll())

        # Phase 4 — WAL recovery: lineage reconstruction with 0 divergences.
        recovery = IntentRecovery(journal=self.journal, event_bus=self.bus)
        analysis = ReplayCoordinator(self.journal).analyze_lineage()
        self.assertEqual(analysis["divergences_detected"], 0)

        pending = recovery.scan_orphaned()
        self.assertIn(intent.intent_id, pending)

        # Phase 5 — filesystem observation + hash comparison -> RECONCILED.
        final_state = recovery.reconcile(intent.intent_id)
        self.assertEqual(final_state, "RECONCILED")

        # The observed effect really is the intended content.
        with open(target, "rb") as f:
            self.assertEqual(_digest(f.read()), expected)

        states, records = self.wal_states(intent.intent_id)
        self.assertEqual(
            states,
            ["QUEUED", "DISPATCHED", "RUNNING", "ORPHANED", "RECOVERING", "RECONCILED"],
        )
        reconcile_payload = records[-1]["payload"]
        self.assertEqual(reconcile_payload.get("expected_sha256"), expected)
        self.assertEqual(reconcile_payload.get("observed_sha256"), expected)
        self.assertTrue(reconcile_payload.get("matched"))

        # Recovery evidence in the runtime event stream.
        events = self.events_for(intent.intent_id)
        invalidations = [
            e for e in events
            if isinstance(e, ExecutionEvent) and e.state == ExecutionState.INVALIDATED
        ]
        self.assertTrue(invalidations)
        verifications = [e for e in events if isinstance(e, VerificationEvent)]
        self.assertTrue(verifications)
        self.assertTrue(verifications[-1].success)

        # Reconciliation is terminal: a second scan finds nothing pending.
        self.assertNotIn(intent.intent_id, recovery.scan_orphaned())

    def test_kernel_crash_before_dispatch_orphans_and_fails_honestly(self):
        """WAL shows RUNNING (durability barrier hit) but no worker frame was
        ever sent — the kernel 'dies' here. Recovery must orphan it, observe
        that NO side effect exists, and fail honestly (not reconcile)."""
        target = os.path.join(self.tmp, "never_written.txt")
        expected = _digest(b"x")
        intent = ExecutionIntent(
            adapter="filesystem",
            operation="write",
            idempotent=False,
            verification_mode=VerificationMode.EXACT,
            rollback_strategy=RollbackMode.NO_ROLLBACK,
            capability_scope={"capability": "filesystem.write"},
            payload={"path": target, "content": "x"},
            intent_id="r1-crash-0002",
            authority_origin="kernel",
        )

        # Durable RUNNING record; then the "kernel" abandons the context
        # without ever sending EXECUTE_REQUEST.
        self.dispatcher.prepare(intent)
        del intent  # simulate process death: in-memory state is gone

        recovery = IntentRecovery(journal=self.journal, event_bus=self.bus)
        pending = recovery.scan_orphaned()
        self.assertIn("r1-crash-0002", pending)

        final_state = recovery.reconcile("r1-crash-0002")
        self.assertEqual(final_state, "FAILED")
        self.assertFalse(os.path.exists(target), "no effect may be invented")

        states, _ = self.wal_states("r1-crash-0002")
        self.assertEqual(
            states,
            ["QUEUED", "DISPATCHED", "RUNNING", "ORPHANED", "RECOVERING", "FAILED"],
        )

        # Failed reconciliation is terminal for recovery purposes.
        self.assertNotIn("r1-crash-0002", recovery.scan_orphaned())


if __name__ == "__main__":
    unittest.main()
