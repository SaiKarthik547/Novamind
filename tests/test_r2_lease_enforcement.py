"""R2-A: CapabilityBroker lease enforcement tests.

Tests the lease security boundary: valid/expiry/revoked leases, intent_id binding,
principal/agent identity, capability grants, target/scope checks, and terminal semantics.
All cases are fail-closed: any invalid/mismatched lease is rejected, never silently allowed.
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.runtime.capability_broker import (
    CapabilityBroker, Capability, ExecutionLease, ResourceBudget
)
from core.runtime.execution_sandbox import ExecutionSandbox, SandboxViolation
from core.runtime.resource_governor import ResourceGovernor


class R2ALeaseTestBase(unittest.TestCase):
    """Shared setup for R2-A lease tests."""

    def setUp(self):
        self.broker = CapabilityBroker()
        self.gov = ResourceGovernor()
        self.sandbox = ExecutionSandbox(broker=self.broker, governor=self.gov)

        self.tmp = tempfile.mkdtemp(prefix="r2_lease_")
        self.test_path = os.path.join(self.tmp, "test_write.txt")

        # Create a valid lease for filesystem.write
        self.valid_lease = self.broker.request_lease(
            task_id="r2-task-001",
            capabilities=[Capability.FILE_WRITE],
            allowed_paths=[self.tmp],
            allowed_commands=["write_file"],
            budget=ResourceBudget(),
            duration_seconds=60.0,
            intent_id="r2-intent-001",
            principal="test-agent",
            agent_id="worker-001",
        )

    def tearDown(self):
        try:
            shutil.rmtree(self.tmp, ignore_errors=True)
        except Exception:
            pass


import shutil


class TestValidLease(R2ALeaseTestBase):
    """R2-A.1: valid lease → execute"""

    def test_valid_lease_allows_execution(self):
        """A valid, non-expired, non-revoked lease should allow the operation."""
        # The sandbox should accept the valid lease
        lease = self.broker.validate_lease(self.valid_lease.lease_id)
        self.assertIsNotNone(lease)
        self.assertTrue(lease.is_valid())
        self.assertEqual(lease.lifecycle_state, "ACTIVE")

        # write_file should succeed with valid lease
        self.sandbox.write_file(
            lease_id=self.valid_lease.lease_id,
            path=self.test_path,
            content="R2-A valid lease test content",
            intent_id="r2-intent-001",
            principal="test-agent",
            agent="worker-001",
        )

        # Verify the file was written
        with open(self.test_path, "r") as f:
            content = f.read()
        self.assertEqual(content, "R2-A valid lease test content")


class TestExpiredLease(R2ALeaseTestBase):
    """R2-A.2: expired lease → reject"""

    def test_expired_lease_is_rejected(self):
        """An expired lease must be rejected (fail-closed)."""
        # Create a lease with very short duration
        expired_lease = self.broker.request_lease(
            task_id="r2-task-002",
            capabilities=[Capability.FILE_WRITE],
            allowed_paths=[self.tmp],
            budget=ResourceBudget(),
            duration_seconds=0.01,  # Immediately expires
            intent_id="r2-intent-002",
        )

        # Wait for expiry
        time.sleep(0.05)

        # validate_lease should return None (not the lease!)
        self.assertIsNone(self.broker.validate_lease(expired_lease.lease_id))

        # Sandbox operations should raise SandboxViolation
        with self.assertRaises(SandboxViolation):
            self.sandbox.write_file(
                lease_id=expired_lease.lease_id,
                path=self.test_path,
                content="should not write",
            )


class TestRevokedLease(R2ALeaseTestBase):
    """R2-A.3: revoked lease → reject"""

    def test_revoked_lease_is_rejected(self):
        """A revoked lease must be rejected (fail-closed)."""
        # Revoke the valid lease
        self.broker.revoke_lease(self.valid_lease.lease_id)

        # validate_lease should return None
        self.assertIsNone(self.broker.validate_lease(self.valid_lease.lease_id))

        # Sandbox should reject
        with self.assertRaises(SandboxViolation):
            self.sandbox.write_file(
                lease_id=self.valid_lease.lease_id,
                path=self.test_path,
                content="should not write after revoke",
            )


class TestWrongIntentId(R2ALeaseTestBase):
    """R2-A.4: wrong intent_id → reject"""

    def test_wrong_intent_id_rejected(self):
        """A lease bound to a different intent_id must be rejected."""
        # Create a lease with a different intent_id
        wrong_intent_lease = self.broker.request_lease(
            task_id="r2-task-003",
            capabilities=[Capability.FILE_WRITE],
            allowed_paths=[self.tmp],
            budget=ResourceBudget(),
            duration_seconds=60.0,
            intent_id="r2-intent-003",  # Different from the one we'll use
            principal="test-agent",
            agent_id="worker-001",
        )

        # Try to use it with the correct intent_id - should fail (strict validation)
        with self.assertRaises(SandboxViolation):
            self.sandbox._verify_lease_strict(
                wrong_intent_lease.lease_id,
                Capability.FILE_WRITE,
                expected_intent_id="r2-intent-001",  # Different intent
            )


class TestWrongCapability(R2ALeaseTestBase):
    """R2-A.5: wrong capability → reject"""

    def test_wrong_capability_rejected(self):
        """A lease that doesn't grant the requested capability must be rejected."""
        # Create a lease with only read capability, try write
        read_only_lease = self.broker.request_lease(
            task_id="r2-task-004",
            capabilities=[Capability.FILE_READ],  # Only read
            allowed_paths=[self.tmp],
            budget=ResourceBudget(),
            duration_seconds=60.0,
            intent_id="r2-intent-004",
        )

        # Try write_file with a read-only lease - should fail
        with self.assertRaises(SandboxViolation):
            self.sandbox.write_file(
                lease_id=read_only_lease.lease_id,
                path=self.test_path,
                content="should not write",
            )


class TestWrongTarget(R2ALeaseTestBase):
    """R2-A.6: wrong target → reject"""

    def test_wrong_target_rejected(self):
        """A lease scoped to one path must reject writes to other paths."""
        # Create a lease scoped to a specific subdirectory
        scoped_lease = self.broker.request_lease(
            task_id="r2-task-005",
            capabilities=[Capability.FILE_WRITE],
            allowed_paths=[os.path.join(self.tmp, "scoped")],  # Only this subdir
            budget=ResourceBudget(),
            duration_seconds=60.0,
            intent_id="r2-intent-005",
        )

        # Try to write outside the scoped path - should fail
        outside_path = os.path.join(self.tmp, "outside.txt")
        with self.assertRaises(SandboxViolation):
            self.sandbox.write_file(
                lease_id=scoped_lease.lease_id,
                path=outside_path,
                content="should not write outside scope",
            )

    def test_correct_target_allowed(self):
        """A lease scoped to a path should allow writes within that scope."""
        scoped_lease = self.broker.request_lease(
            task_id="r2-task-006",
            capabilities=[Capability.FILE_WRITE],
            allowed_paths=[os.path.join(self.tmp, "scoped")],
            budget=ResourceBudget(),
            duration_seconds=60.0,
            intent_id="r2-intent-006",
        )

        # Write within the scoped path - should succeed
        os.makedirs(os.path.join(self.tmp, "scoped"), exist_ok=True)
        scoped_path = os.path.join(self.tmp, "scoped", "write.txt")
        self.sandbox.write_file(
            lease_id=scoped_lease.lease_id,
            path=scoped_path,
            content="scoped write OK",
        )

        with open(scoped_path, "r") as f:
            content = f.read()
        self.assertEqual(content, "scoped write OK")


class TestWrongWorker(R2ALeaseTestBase):
    """R2-A.7: wrong worker → reject"""

    def test_wrong_worker_rejected(self):
        """A lease bound to a specific agent/worker must reject other workers."""
        # Create a lease bound to worker-001
        worker_lease = self.broker.request_lease(
            task_id="r2-task-007",
            capabilities=[Capability.FILE_WRITE],
            allowed_paths=[self.tmp],
            budget=ResourceBudget(),
            duration_seconds=60.0,
            intent_id="r2-intent-007",
            principal="test-agent",
            agent_id="worker-001",  # Bound to worker-001
        )

        # Try to use it as worker-002 - should fail (strict validation)
        with self.assertRaises(SandboxViolation):
            self.sandbox._verify_lease_strict(
                worker_lease.lease_id,
                Capability.FILE_WRITE,
                expected_agent="worker-002",  # Different worker
            )


class TestMissingLease(R2ALeaseTestBase):
    """R2-A.8: missing lease → reject"""

    def test_missing_lease_rejected(self):
        """A non-existent lease must be rejected."""
        nonexistent_id = "nonexistent-lease-id-12345"

        # validate_lease should return None
        self.assertIsNone(self.broker.validate_lease(nonexistent_id))

        # Sandbox should reject
        with self.assertRaises(SandboxViolation):
            self.sandbox.write_file(
                lease_id=nonexistent_id,
                path=self.test_path,
                content="should not write without lease",
            )


class TestLeaseExpiresBetweenGovernanceAndDispatch(R2ALeaseTestBase):
    """R2-A.9: lease expires between governance and dispatch → reject"""

    def test_lease_expires_between_gov_and_dispatch(self):
        """A lease that expires between governance validation and worker dispatch must be rejected."""
        # Create a lease with very short duration
        transient_lease = self.broker.request_lease(
            task_id="r2-task-008",
            capabilities=[Capability.FILE_WRITE],
            allowed_paths=[self.tmp],
            budget=ResourceBudget(),
            duration_seconds=0.01,
            intent_id="r2-intent-008",
        )

        # Simulate: governance validates it (is_valid returns True at that moment)
        # but by the time the worker tries to use it, it has expired
        time.sleep(0.05)  # Let it expire

        # Now validate - should fail closed
        self.assertIsNone(self.broker.validate_lease(transient_lease.lease_id))

        # Sandbox should reject
        with self.assertRaises(SandboxViolation):
            self.sandbox.write_file(
                lease_id=transient_lease.lease_id,
                path=self.test_path,
                content="should not write after expiry gap",
            )


class TestTerminalLeaseSemantics(R2ALeaseTestBase):
    """R2-A.10: terminal behavior explicit"""

    def test_terminal_states_have_deterministic_lease_semantics(self):
        """COMPLETED, FAILED, CANCELLED, ORPHANED must have deterministic lease semantics."""
        import shutil

        # Create a lease and write the file first
        completed_lease = self.broker.request_lease(
            task_id="r2-task-010",
            capabilities=[Capability.FILE_WRITE],
            allowed_paths=[self.tmp],
            budget=ResourceBudget(),
            duration_seconds=60.0,
            intent_id="r2-intent-010",
        )

        # Write the file first
        self.sandbox.write_file(
            lease_id=completed_lease.lease_id,
            path=self.test_path,
            content="terminal test",
        )

        # Now terminalize the lease as COMPLETED
        self.broker.terminalize_lease(completed_lease.lease_id, "COMPLETED")

        # Validate should reject - terminal leases cannot authorize effects
        with self.assertRaises(SandboxViolation):
            self.sandbox.write_file(
                lease_id=completed_lease.lease_id,
                path=self.test_path,
                content="should not write on terminal lease",
            )

        # FAILED state
        failed_lease = self.broker.request_lease(
            task_id="r2-task-011",
            capabilities=[Capability.FILE_WRITE],
            allowed_paths=[self.tmp],
            budget=ResourceBudget(),
            duration_seconds=60.0,
            intent_id="r2-intent-011",
        )

        # Terminalize as FAILED
        self.broker.terminalize_lease(failed_lease.lease_id, "FAILED")
        # Validate should reject
        with self.assertRaises(SandboxViolation):
            self.sandbox.write_file(
                lease_id=failed_lease.lease_id,
                path=self.test_path,
                content="should not write on terminal lease",
            )

        # CANCELLED state
        cancelled_lease = self.broker.request_lease(
            task_id="r2-task-012",
            capabilities=[Capability.FILE_WRITE],
            allowed_paths=[self.tmp],
            budget=ResourceBudget(),
            duration_seconds=60.0,
            intent_id="r2-intent-012",
        )

        # Terminalize as CANCELLED
        self.broker.terminalize_lease(cancelled_lease.lease_id, "CANCELLED")
        # Validate should reject
        with self.assertRaises(SandboxViolation):
            self.sandbox.write_file(
                lease_id=cancelled_lease.lease_id,
                path=self.test_path,
                content="should not write on terminal lease",
            )

        # ORPHANED state (from crash recovery)
        orphaned_lease = self.broker.request_lease(
            task_id="r2-task-013",
            capabilities=[Capability.FILE_WRITE],
            allowed_paths=[self.tmp],
            budget=ResourceBudget(),
            duration_seconds=60.0,
            intent_id="r2-intent-013",
        )

        # Terminalize as ORPHANED
        self.broker.terminalize_lease(orphaned_lease.lease_id, "ORPHANED")
        # Validate should reject
        with self.assertRaises(SandboxViolation):
            self.sandbox.write_file(
                lease_id=orphaned_lease.lease_id,
                path=self.test_path,
                content="should not write on terminal lease",
            )


if __name__ == "__main__":
    unittest.main()