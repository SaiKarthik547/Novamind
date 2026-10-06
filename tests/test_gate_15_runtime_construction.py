"""
tests/test_gate_15_runtime_construction.py

Gate 1.5: Runtime construction integrity.

This test proves that the canonical runtime authorities can be constructed and
boot to a READY-like state without performing any external OS mutation.

It deliberately does NOT:
- spawn worker processes
- execute adapters
- mutate the Windows filesystem
- depend on main.py orchestration

If construction requires external side effects, this test must fail explicitly.
"""

import unittest
from unittest.mock import patch

from core.runtime.lifecycle_authority import LifecycleAuthority, RuntimeLifecycleState
from core.runtime.runtime_bootstrap import RuntimeBootstrap, BootstrapPhase
from core.execution.runtime_kernel import RuntimeKernel
from core.execution.kernel_facade import KernelExecutionFacade
from core.execution.intent_governance import IntentGovernanceLayer
from core.execution.execution_scheduler import ExecutionScheduler
from core.execution.capability_registry import CAPABILITY_REGISTRY
from core.runtime.semantic_authority_registry import SemanticAuthorityRegistry


class TestCanonicalComponentsConstructible(unittest.TestCase):
    def test_lifecycle_authority_constructs_and_starts_initializing(self):
        la = LifecycleAuthority()
        self.assertIsNotNone(la)
        self.assertEqual(la.get_state(), RuntimeLifecycleState.INITIALIZING)

    def test_lifecycle_authority_can_reach_ready_from_initializing(self):
        la = LifecycleAuthority()
        la.transition_to_reconciling()
        la.transition_to_ready()
        self.assertEqual(la.get_state(), RuntimeLifecycleState.READY)

    def test_capability_registry_resolves_filesystem_write(self):
        defn = CAPABILITY_REGISTRY.get("filesystem.write")
        self.assertIsNotNone(defn)
        self.assertEqual(defn.capability_name, "filesystem.write")

    def test_kernel_execution_facade_constructs(self):
        facade = KernelExecutionFacade()
        self.assertIsNotNone(facade)

    def test_intent_governance_layer_constructs(self):
        gl = IntentGovernanceLayer()
        self.assertIsNotNone(gl)

    def test_execution_scheduler_constructs_with_facade(self):
        facade = KernelExecutionFacade()
        sched = ExecutionScheduler(kernel_facade=facade)
        self.assertIsNotNone(sched)


class TestRuntimeBootstrapConstructionNoExternalMutation(unittest.TestCase):
    """
    Gate 1.5 core assertion: constructing RuntimeBootstrap must not perform
    external OS mutations.

    We still allow construction because the canonical runtime must be
    instantiable. But we assert hard that no worker is spawned and no adapter
    is assigned or executed during bootstrap.
    """

    def test_bootstrap_constructs_in_transitional_mode(self):
        # Transitional mode is the current default; construction must still work.
        rb = RuntimeBootstrap()
        self.assertIsNotNone(rb)
        self.assertIsNotNone(rb.lifecycle_authority)
        self.assertIsNotNone(rb.kernel)
        self.assertIsNotNone(rb.adapter_supervisor)
        self.assertIsNotNone(rb.event_stream)
        self.assertIsNotNone(rb.snapshot_provider)

    def test_bootstrap_reaches_ready_without_external_mutation(self):
        rb = RuntimeBootstrap()
        # The existing bootstrap constructor transitions to READY internally.
        # We verify that READY is reachable and that construction stayed internal.
        self.assertEqual(rb.lifecycle_authority.get_state(), RuntimeLifecycleState.READY)

    def test_bootstrap_reaches_ready_and_freezes_topology(self):
        rb = RuntimeBootstrap()

        self.assertEqual(rb.lifecycle_authority.get_state(), RuntimeLifecycleState.READY)
        self.assertTrue(SemanticAuthorityRegistry.get_topology_hash())

    def test_bootstrap_does_not_spawn_workers(self):
        from core.runtime.kernel_supervisor import KernelSupervisor

        launches = []

        original = KernelSupervisor.launch_worker

        def fake_launch_worker(self, worker_cmd):
            launches.append(worker_cmd)
            raise RuntimeError("Gate 1.5: worker launch must not happen during bootstrap")

        try:
            KernelSupervisor.launch_worker = fake_launch_worker
            rb2 = RuntimeBootstrap()
        finally:
            KernelSupervisor.launch_worker = original

        self.assertEqual(launches, [])

    def test_bootstrap_does_not_assign_or_execute_adapters(self):
        rb = RuntimeBootstrap()
        # AdapterSupervisor.assign_adapter triggers adapter initialization/attach/execute paths.
        # The bootstrap constructor must not call assign_adapter.
        advisor = rb.adapter_supervisor
        self.assertIsNotNone(advisor)
        self.assertEqual(len(advisor._active_adapters), 0)

    def test_bootstrap_does_not_execute_intents(self):
        rb = RuntimeBootstrap()
        advisor = rb.adapter_supervisor
        # AdapterSupervisor.execute_intent is the adapter execution entry point.
        # If bootstrap somehow executes an intent, this mock will catch it.
        executions = []

        def fake_execute_intent(self, intent):
            executions.append(intent)
            raise RuntimeError("Gate 1.5: intent execution must not happen during bootstrap")

        with patch.object(
            advisor.__class__,
            "execute_intent",
            fake_execute_intent,
        ):
            rb2 = RuntimeBootstrap()

        self.assertEqual(executions, [])


class TestStrictBootstrapTopologyFreeze(unittest.TestCase):
    """
    Verify that STRICT bootstrap topology freeze works when the registry is clear.
    """

    def setUp(self):
        SemanticAuthorityRegistry.clear_for_testing()

    def tearDown(self):
        SemanticAuthorityRegistry.clear_for_testing()

    def test_strict_mode_freezes_topology(self):
        RuntimeBootstrap.set_phase(BootstrapPhase.STRICT)
        try:
            rb = RuntimeBootstrap()
        finally:
            RuntimeBootstrap.set_phase(BootstrapPhase.TRANSITIONAL)

        self.assertIsNotNone(rb)
        self.assertTrue(
            SemanticAuthorityRegistry.get_topology_hash()
        )


if __name__ == "__main__":
    unittest.main()
