import logging
from enum import Enum, auto
from typing import Dict, Any, Callable, Optional, Set

logger = logging.getLogger(__name__)

# ── Modes ─────────────────────────────────────────────────────────────────────

class SupervisorMode(Enum):
    NORMAL = auto()
    DEGRADED = auto()
    QUARANTINED = auto()
    RECOVERY = auto()
    HALTED = auto()

# ── Formal Transition Table ───────────────────────────────────────────────────

# Dict[CurrentMode, Dict[Event, NextMode]]
FSM_TRANSITIONS = {
    SupervisorMode.NORMAL: {
        "CHECKSUM_MISMATCH": SupervisorMode.DEGRADED,
        "IPC_DISCONNECT": SupervisorMode.DEGRADED,
        "AGENT_VIOLATION": SupervisorMode.QUARANTINED,
        "CRITICAL_CORRUPTION": SupervisorMode.HALTED,
    },
    SupervisorMode.DEGRADED: {
        "RECONCILIATION_COMPLETE": SupervisorMode.NORMAL,
        "REPLAY_FAILURE": SupervisorMode.RECOVERY,
        "CRITICAL_CORRUPTION": SupervisorMode.HALTED,
    },
    SupervisorMode.QUARANTINED: {
        "AGENT_ISOLATED": SupervisorMode.DEGRADED, # Drop to degraded until full sync
        "REPLAY_FAILURE": SupervisorMode.RECOVERY,
        "CRITICAL_CORRUPTION": SupervisorMode.HALTED,
    },
    SupervisorMode.RECOVERY: {
        "RECOVERY_SUCCESS": SupervisorMode.NORMAL,
        "UNRECOVERABLE_DIVERGENCE": SupervisorMode.HALTED,
        "CRITICAL_CORRUPTION": SupervisorMode.HALTED,
    },
    SupervisorMode.HALTED: {
        # Terminal state. Requires hard process restart.
    }
}

# ── Internal Layers ───────────────────────────────────────────────────────────

class RuntimeStateMachine:
    """Enforces legal runtime mode transitions."""
    def __init__(self):
        self.mode = SupervisorMode.NORMAL
        
    def transition(self, event: str) -> bool:
        allowed = FSM_TRANSITIONS.get(self.mode, {})
        next_mode = allowed.get(event)
        
        if next_mode:
            logger.warning(f"[FSM] Transition: {self.mode.name} -> {event} -> {next_mode.name}")
            self.mode = next_mode
            return True
            
        logger.error(f"[FSM] Illegal transition requested: {self.mode.name} cannot handle {event}")
        return False

class EscalationHandler:
    """Classifies invariant violations into FSM events."""
    
    @staticmethod
    def classify(violation: dict) -> str:
        code = violation.get("code", "")
        
        if code in ("HEARTBEAT_GHOST_TASKS", "HEARTBEAT_UNKNOWN_TASKS", "DIVERGENCE_DETECTED"):
            return "CHECKSUM_MISMATCH"
            
        if code in ("ILLEGAL_TASK_TRANSITION", "UNKNOWN_CAUSAL_PARENT"):
            return "CRITICAL_CORRUPTION" # Semantic timeline is broken
            
        if code in ("AGENT_DOUBLE_CREATE", "AGENT_DESTROY_UNKNOWN"):
            return "AGENT_VIOLATION"
            
        if code == "MSG_ID_DUPLICATE":
            # Idempotency cache usually drops these, if it hits auditor, network is acting up
            return "IPC_DISCONNECT"
            
        return "CRITICAL_CORRUPTION" # Default to unsafe

class HealthEvaluator:
    """Evaluates divergence scores against thresholds."""
    
    @staticmethod
    def is_degraded(score: float) -> bool:
        return score < 0.95
        
    @staticmethod
    def requires_recovery(score: float) -> bool:
        return score < 0.80

class RecoveryCoordinator:
    """Orchestrates rebuild actions (snapshots, replays)."""
    def __init__(self, snapshot_mgr, replay_engine):
        self.snapshot_mgr = snapshot_mgr
        self.replay_engine = replay_engine
        
    def trigger_rebuild(self) -> bool:
        logger.info("[RecoveryCoordinator] Triggering full state rebuild...")
        # To be fully wired in Phase 6 incrementally
        return False

# ── Main Supervisor (Policy Engine) ───────────────────────────────────────────

class RuntimeSupervisor:
    """
    Ultimate policy authority for the NovaMind distributed runtime.
    The Auditor reports violations here; the Supervisor dictates the response.
    """
    def __init__(self, event_bus: Any, event_recorder: Any):
        self.event_bus = event_bus
        self.event_recorder = event_recorder
        
        self.fsm = RuntimeStateMachine()
        self.escalation = EscalationHandler()
        self.health = HealthEvaluator()
        self.recovery: Optional[RecoveryCoordinator] = None
        
        # Quarantined agents
        self.isolated_agents: Set[str] = set()

    def set_recovery_coordinator(self, coordinator: RecoveryCoordinator):
        self.recovery = coordinator

    def on_violation(self, violation: dict):
        """Callback wired to the RuntimeAuditor."""
        violation_num = violation.get('violation_number', '?')
        code = violation.get('code', 'UNKNOWN')
        msg = violation.get('message', '')
        
        logger.critical(f"[Supervisor] INVARIANT VIOLATION #{violation_num} [{code}]: {msg}")
        
        # 1. Log durably
        if self.event_recorder:
            self.event_recorder.log_event(
                event_type="INVARIANT_VIOLATION",
                source_runtime="Python:RuntimeSupervisor",
                severity="CRITICAL",
                payload=violation,
            )
            
        # 2. Classify and escalate
        fsm_event = self.escalation.classify(violation)
        success = self.fsm.transition(fsm_event)
        
        # 3. Apply Policy based on new state
        if self.fsm.mode == SupervisorMode.QUARANTINED:
            agent_id = violation.get("payload", {}).get("agent_id")
            if agent_id:
                self.isolate_agent(agent_id)
                self.fsm.transition("AGENT_ISOLATED")
                
        elif self.fsm.mode == SupervisorMode.DEGRADED:
            # Trigger reconciliation (tell Godot we are desynced)
            self.event_bus.publish({
                "type": "STATE_DIVERGENCE",
                "severity": "WARNING",
                "message": "Entering DEGRADED mode due to invariant violation."
            })
            
        elif self.fsm.mode == SupervisorMode.RECOVERY:
            if self.recovery:
                success = self.recovery.trigger_rebuild()
                if not success:
                    self.fsm.transition("UNRECOVERABLE_DIVERGENCE")
            else:
                self.fsm.transition("UNRECOVERABLE_DIVERGENCE")
                
        elif self.fsm.mode == SupervisorMode.HALTED:
            self._halt_runtime()

    def isolate_agent(self, agent_id: str):
        logger.warning(f"[Supervisor] Quarantining agent: {agent_id}")
        self.isolated_agents.add(agent_id)
        # Publish internal event so TaskManager stops routing to it
        self.event_bus.publish({
            "type": "AGENT_QUARANTINED",
            "agent_id": agent_id
        })

    def _halt_runtime(self):
        logger.fatal("[Supervisor] RUNTIME HALTED. Critical semantic corruption. Restart required.")
        # We don't exit() directly to allow graceful flush, but we lock the event bus if possible
        # Emitting HALT event
        self.event_bus.publish({
            "type": "RUNTIME_HALTED",
            "reason": "Unrecoverable semantic corruption."
        })
