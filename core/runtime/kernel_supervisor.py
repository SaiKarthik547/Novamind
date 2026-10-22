import logging
from typing import Dict, Optional

from core.runtime.capability_broker import CapabilityBroker
from core.runtime.worker_runtime import WorkerSupervisor
from core.ipc.worker_protocol import WorkerIdentity, WorkerState
from core.execution.recovery_journal import RecoveryJournal
from core.replay.replay_coordinator import ReplayCoordinator
from core.transaction.panic_manager import PanicManager, PanicLevel

logger = logging.getLogger("KernelSupervisor")

class KernelSupervisor:
    """
    TRANSITIONAL top-level supervisor for isolated worker execution.

    This class is NOT the canonical runtime kernel for the convergence program.
    Canonical authority lives in core.execution.runtime_kernel.RuntimeKernel and
    core.runtime.lifecycle_authority.LifecycleAuthority.

    This module is retained only until the canonical bootstrap/kernel path is proven.
    """
    def __init__(self, wal_path: str = "nova_effect.wal", event_bus=None):
        # Use the execution-side canonical RecoveryJournal rather than a competing transaction WAL.
        self.wal = RecoveryJournal(wal_path)
        self.reconciler = ReplayCoordinator(self.wal)
        self.event_bus = event_bus
        self.workers: Dict[str, WorkerSupervisor] = {}

        # Canonical R2-A: one persistent CapabilityBroker authority for all leases.
        # The dispatcher injects this same broker so the worker can validate
        # against current authority rather than stale copied metadata.
        self.broker = CapabilityBroker()

        # Re-establish the panic delegation point expected by the active bootstrap path.
        # This is transitional. It must not become a second panic authority.
        self.panic_manager = PanicManager(
            kernel_supervisor=self,
            lifecycle_authority=None,
        )

    def _reconcile_on_boot(self):
        logger.info("KernelSupervisor booting: Beginning WAL reconciliation.")
        try:
            reconciliation_states = self.reconciler.analyze_lineage()
            for tx_id, info in reconciliation_states.get("intents", {}).items():
                logger.info(f"Reconciliation for TX {tx_id}: {info.get('state')}")
        except Exception as e:
            logger.error(f"Boot reconciliation failed: {e}")

    def launch_worker(self, worker_cmd: list[str]) -> str:
        identity = WorkerIdentity()
        supervisor = WorkerSupervisor(worker_cmd, identity)
        self.workers[identity.worker_id] = supervisor
        supervisor.start()
        return identity.worker_id

    def stop_worker(self, worker_id: str):
        worker = self.workers.get(worker_id)
        if worker:
            worker.stop()

    def quarantine_worker(self, worker_id: str):
        worker = self.workers.get(worker_id)
        if worker:
            worker.state = WorkerState.TAINTED
            logger.warning(f"Worker {worker_id} quarantined.")

    def freeze_scheduler(self):
        logger.warning("KernelSupervisor: Scheduler dispatch frozen.")

    def halt_and_catch_fire(self, flush_wal: bool = False):
        if flush_wal and self.wal:
            self.wal.close()
        for worker in list(self.workers.values()):
            try:
                worker.stop()
            except Exception:
                pass
        logger.critical("KernelSupervisor HALTED.")
