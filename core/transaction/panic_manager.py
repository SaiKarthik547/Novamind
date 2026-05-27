import logging
from enum import Enum
import sys

logger = logging.getLogger("PanicManager")

class PanicLevel(Enum):
    RECOVERABLE = "RECOVERABLE"
    QUARANTINE = "QUARANTINE"
    FATAL = "FATAL"
    CONTAINMENT_BREACH = "CONTAINMENT_BREACH"


class PanicManager:
    """
    Formal runtime failure semantics to classify and handle system panics.
    Defines explicit freeze semantics for different panic levels.
    """
    def __init__(self, kernel_supervisor=None, lifecycle_authority=None):
        self.kernel_supervisor = kernel_supervisor
        self.lifecycle_authority = lifecycle_authority

    def invoke_panic(self, level: PanicLevel, reason: str, worker_id: str = None):
        logger.critical(f"KERNEL PANIC [{level.value}]: {reason}")
        
        if level == PanicLevel.RECOVERABLE:
            # Freeze: Offending Worker IPC
            # Keep alive: Scheduler, WAL, Replay, Other Workers
            logger.info("Panic strategy: Restarting offending worker and re-dispatching safe transactions.")
            if self.kernel_supervisor and worker_id:
                self.kernel_supervisor.quarantine_worker(worker_id)
                
        elif level == PanicLevel.QUARANTINE:
            # Freeze: Offending Worker, Scheduler Dispatch
            # Keep alive: WAL, IPC (for graceful drain), Other Workers (to finish current tx)
            logger.error("Panic strategy: Freezing scheduler dispatch. Draining active workers. Quarantining state.")
            if self.lifecycle_authority:
                self.lifecycle_authority.transition_to_degraded(reason=reason)
            if self.kernel_supervisor:
                self.kernel_supervisor.freeze_scheduler()
                if worker_id:
                    self.kernel_supervisor.quarantine_worker(worker_id)
                    
        elif level == PanicLevel.FATAL:
            # Freeze: Scheduler, All Workers, IPC
            # Keep alive: WAL (to flush final state)
            logger.critical("Panic strategy: Escalating FATAL panic to lifecycle authority.")
            if self.lifecycle_authority:
                self.lifecycle_authority.trigger_panic(reason=reason)
            
            if self.kernel_supervisor:
                self.kernel_supervisor.halt_and_catch_fire(flush_wal=True)
                sys.exit(1)
            
        elif level == PanicLevel.CONTAINMENT_BREACH:
            # Freeze: EVERYTHING IMMEDIATELY
            logger.critical("Panic strategy: IMMEDIATE PROCESS ABORT. CONTAINMENT BREACH DETECTED.")
            # Do NOT even attempt to flush WAL gracefully if containment is breached,
            # as WAL writes themselves might be compromised.
            import os
            os._exit(1)
