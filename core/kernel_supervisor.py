import logging
from typing import Dict, Optional

from core.worker_runtime import WorkerSupervisor
from core.worker_protocol import WorkerIdentity, WorkerState
from core.transaction.effect_wal import EffectWal
from core.transaction.effect_reconciler import EffectReconciler
from core.transaction.panic_manager import PanicManager, PanicLevel
from core.transaction.transaction_manager import TransactionManager
from core.orchestration.causal_scheduler import CausalScheduler

logger = logging.getLogger("KernelSupervisor")

class KernelSupervisor:
    """
    The top-level authority for the Isolated Execution Kernel.
    Takes ownership of all state transitions, workers, transactions, and panics.
    The Brain now delegates OS-level authority to this class.
    """
    def __init__(self, wal_path: str = "nova_effect.wal"):
        self.wal = EffectWal(wal_path)
        self.reconciler = EffectReconciler(self.wal)
        self.panic_manager = PanicManager(self)
        self.transaction_manager = TransactionManager(self.wal)
        self.scheduler = CausalScheduler()
        
        self.workers: Dict[str, WorkerSupervisor] = {}
        
        # On boot, reconcile crash state
        self._reconcile_on_boot()

    def _reconcile_on_boot(self):
        logger.info("KernelSupervisor booting: Beginning WAL reconciliation.")
        try:
            reconciliation_states = self.reconciler.analyze()
            for tx_id, state in reconciliation_states.items():
                logger.info(f"Reconciliation for TX {tx_id}: {state.value}")
        except Exception as e:
            self.panic_manager.invoke_panic(PanicLevel.FATAL, f"Boot reconciliation failed: {e}")

    def launch_worker(self, worker_cmd: list[str]) -> str:
        identity = WorkerIdentity()
        # In a real system, we assign a secure nonce and pass it via env or stdin securely
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
        # Actually pause the CausalScheduler's event loop
        # Implementation depends on scheduler interface
        pass

    def halt_and_catch_fire(self, flush_wal: bool = False):
        if flush_wal and self.wal:
            self.wal.close()
        for worker in self.workers.values():
            worker.stop()
        logger.critical("KernelSupervisor HALTED.")
