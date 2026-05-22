import logging
from typing import Any, Dict, List
from dataclasses import dataclass, field
from core.capability_broker import ExecutionLease
from core.transaction_manager import TransactionManager, TransactionType
from core.execution_sandbox import ExecutionSandbox

logger = logging.getLogger("AgentContext")


@dataclass
class AgentContext:
    """
    Provides agents with a scoped, capability-checked execution environment.
    Agents MUST use this context to perform any real-world side effects.
    """
    task_id: str
    step_number: int
    agent_id: str
    action: str
    parameters: Dict[str, Any]
    
    lease: ExecutionLease
    sandbox: ExecutionSandbox
    transaction_manager: TransactionManager

    kernel_supervisor: Any = None # Phase 9 Delegate

    # Telemetry data that the agent might want to read, 
    # but not modify.
    telemetry_tags: Dict[str, str] = field(default_factory=dict)
    
    def begin_transaction(self, tx_type: TransactionType) -> str:
        """Starts a transaction for an effect."""
        return self.transaction_manager.begin(
            task_id=self.task_id,
            agent_id=self.agent_id,
            action=self.action,
            tx_type=tx_type
        )
        
    def execute_transaction(self, tx_id: str, payload: Dict[str, Any], execute_fn: callable) -> Dict[str, Any]:
        """
        Executes a transaction through its full lifecycle.
        execute_fn must take `self.sandbox` and `self.lease.lease_id` as arguments.
        """
        if not self.transaction_manager.journal(tx_id, payload):
            return {"success": False, "error": "Failed to journal transaction"}
            
        if not self.transaction_manager.authorize(tx_id, self.lease.lease_id):
            return {"success": False, "error": "Failed to authorize transaction"}
            
        if not self.transaction_manager.mark_executing(tx_id):
            return {"success": False, "error": "Failed to transition to EXECUTE state"}
            
        try:
            # The agent's actual effect execution via sandbox
            result = execute_fn(self.sandbox, self.lease.lease_id)
            
            # Post-execution verification
            self.transaction_manager.verify(tx_id, compensation_data=result.get("compensation_data", {}))
            self.transaction_manager.commit(tx_id)
            return {"success": True, "data": result}
            
        except Exception as e:
            logger.error(f"Transaction {tx_id[:8]} failed during execution: {e}")
            self.transaction_manager.rollback(tx_id, reason=str(e))
            return {"success": False, "error": str(e)}

    # Convenience wrappers for common operations
    def run_subprocess(self, command: List[str] | str, tx_type: TransactionType = TransactionType.IRREVERSIBLE, **kwargs) -> Dict:
        tx_id = self.begin_transaction(tx_type)
        payload = {"command": command}
        
        def _exec(sandbox, lease_id):
            proc = sandbox.run_subprocess(lease_id, command, **kwargs)
            stdout, stderr = proc.communicate(timeout=kwargs.get("timeout", 60))
            return {"stdout": stdout, "stderr": stderr, "returncode": proc.returncode}
            
        return self.execute_transaction(tx_id, payload, _exec)
