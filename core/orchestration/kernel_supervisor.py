import logging
from typing import Any, Optional, Set

from core.contracts.runtime_states import RuntimeState
from core.bootstrap.runtime_lifecycle import RuntimeLifecycle

logger = logging.getLogger(__name__)

class EscalationHandler:
    @staticmethod
    def classify(violation: dict) -> RuntimeState:
        code = violation.get('code', '')
        if code in ('HEARTBEAT_GHOST_TASKS', 'HEARTBEAT_UNKNOWN_TASKS', 'DIVERGENCE_DETECTED'):
            return RuntimeState.DEGRADED
        if code in ('ILLEGAL_TASK_TRANSITION', 'UNKNOWN_CAUSAL_PARENT'):
            return RuntimeState.PANIC
        if code in ('AGENT_DOUBLE_CREATE', 'AGENT_DESTROY_UNKNOWN'):
            return RuntimeState.DEGRADED
        if code == 'MSG_ID_DUPLICATE':
            return RuntimeState.DEGRADED
        return RuntimeState.PANIC

class KernelSupervisor:
    def __init__(self, lifecycle: RuntimeLifecycle, event_bus: Any, event_recorder: Any):
        self.lifecycle = lifecycle
        self.event_bus = event_bus
        self.event_recorder = event_recorder
        self.escalation = EscalationHandler()
        self.isolated_agents: Set[str] = set()
        self.recovery = None

    def set_recovery_coordinator(self, coordinator):
        self.recovery = coordinator

    def on_violation(self, violation: dict):
        violation_num = violation.get('violation_number', '?')
        code = violation.get('code', 'UNKNOWN')
        msg = violation.get('message', '')
        
        logger.critical(f'[KernelSupervisor] INVARIANT VIOLATION #{violation_num} [{code}]: {msg}')
        
        if self.event_recorder:
            self.event_recorder.log_event(
                event_type='INVARIANT_VIOLATION',
                source_runtime='Python:KernelSupervisor',
                severity='CRITICAL',
                payload=violation,
            )
            
        target_state = self.escalation.classify(violation)
        try:
            self.lifecycle.transition(target_state, reason=f'Invariant violation: {code}')
        except Exception as e:
            logger.error(f'Failed to escalate state: {e}')
            return

        if self.lifecycle.current_state == RuntimeState.DEGRADED:
            self.event_bus.publish({
                'type': 'STATE_DIVERGENCE',
                'severity': 'WARNING',
                'message': 'Entering DEGRADED mode due to invariant violation.'
            })
        elif self.lifecycle.current_state == RuntimeState.PANIC:
            self._panic_runtime()

    def isolate_agent(self, agent_id: str):
        logger.warning(f'[KernelSupervisor] Quarantining agent: {agent_id}')
        self.isolated_agents.add(agent_id)
        self.event_bus.publish({
            'type': 'AGENT_QUARANTINED',
            'agent_id': agent_id
        })

    def _panic_runtime(self):
        logger.fatal('[KernelSupervisor] RUNTIME PANIC. Critical semantic corruption. Halting.')
        self.event_bus.publish({
            'type': 'RUNTIME_HALTED',
            'reason': 'Unrecoverable semantic corruption.'
        })
        self.lifecycle.transition(RuntimeState.HALT, reason='Panic triggered halt')
