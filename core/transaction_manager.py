import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional

logger = logging.getLogger("TransactionManager")

class TransactionType(Enum):
    REVERSIBLE       = "REVERSIBLE"       # True inverse exists (e.g., create temp file -> delete temp file)
    COMPENSATABLE    = "COMPENSATABLE"    # Semantic undo (e.g., refund after charge)
    IRREVERSIBLE     = "IRREVERSIBLE"     # Cannot safely undo (e.g., send email)
    OBSERVATIONAL    = "OBSERVATIONAL"    # Read-only (e.g., list dir)
    NONDETERMINISTIC = "NONDETERMINISTIC" # Replay unsafe, outcomes vary (e.g., random generation, external API)


class TransactionState(Enum):
    PREPARE   = "PREPARE"
    JOURNAL   = "JOURNAL"
    AUTHORIZE = "AUTHORIZE"
    EXECUTE   = "EXECUTE"
    VERIFY    = "VERIFY"
    COMMIT    = "COMMIT"
    ROLLBACK  = "ROLLBACK"
    TAINTED   = "TAINTED"   # Mid-execution crash or irreversible failure


@dataclass
class TransactionRecord:
    tx_id: str
    task_id: str
    agent_id: str
    action: str
    tx_type: TransactionType
    state: TransactionState = TransactionState.PREPARE
    payload: Dict[str, Any] = field(default_factory=dict)
    compensation_data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class TransactionManager:
    """
    Manages the lifecycle of agent side-effects.
    Enforces PREPARE -> JOURNAL -> AUTHORIZE -> EXECUTE -> VERIFY -> COMMIT.
    """
    def __init__(self, state_manager=None, capability_broker=None):
        self.state_manager = state_manager
        self.capability_broker = capability_broker
        self._active_txs: Dict[str, TransactionRecord] = {}
        self._journal: List[TransactionRecord] = []

    def begin(self, task_id: str, agent_id: str, action: str, tx_type: TransactionType) -> str:
        tx_id = str(uuid.uuid4())
        tx = TransactionRecord(
            tx_id=tx_id,
            task_id=task_id,
            agent_id=agent_id,
            action=action,
            tx_type=tx_type,
            state=TransactionState.PREPARE
        )
        self._active_txs[tx_id] = tx
        logger.debug(f"TX {tx_id[:8]} BEGIN ({tx_type.value}) for {agent_id}.{action}")
        return tx_id

    def journal(self, tx_id: str, payload: Dict[str, Any]) -> bool:
        tx = self._active_txs.get(tx_id)
        if not tx or tx.state != TransactionState.PREPARE:
            return False
        
        tx.payload = payload
        tx.state = TransactionState.JOURNAL
        self._journal.append(tx)
        
        if self.state_manager:
            # Sync to durable storage BEFORE execution
            # This is critical for mid-execution crash reconciliation
            self.state_manager.execute("INSERT INTO _tx_journal (tx_id, state) VALUES (?, ?)", (tx_id, tx.state.value))
            
        logger.debug(f"TX {tx_id[:8]} JOURNALED")
        return True

    def authorize(self, tx_id: str, lease_id: str) -> bool:
        tx = self._active_txs.get(tx_id)
        if not tx or tx.state != TransactionState.JOURNAL:
            return False
        
        if self.capability_broker:
            lease = self.capability_broker.validate_lease(lease_id)
            if not lease:
                tx.error = "Invalid or expired lease"
                self.rollback(tx_id)
                return False
                
        tx.state = TransactionState.AUTHORIZE
        logger.debug(f"TX {tx_id[:8]} AUTHORIZED")
        return True

    def mark_executing(self, tx_id: str) -> bool:
        tx = self._active_txs.get(tx_id)
        if not tx or tx.state != TransactionState.AUTHORIZE:
            return False
        
        tx.state = TransactionState.EXECUTE
        if self.state_manager:
            self.state_manager.execute("UPDATE _tx_journal SET state = ? WHERE tx_id = ?", (tx.state.value, tx_id))
        logger.debug(f"TX {tx_id[:8]} EXECUTING")
        return True

    def verify(self, tx_id: str, compensation_data: Dict[str, Any] = None) -> bool:
        tx = self._active_txs.get(tx_id)
        if not tx or tx.state != TransactionState.EXECUTE:
            return False
        
        tx.state = TransactionState.VERIFY
        if compensation_data:
            tx.compensation_data = compensation_data
        logger.debug(f"TX {tx_id[:8]} VERIFIED")
        return True

    def commit(self, tx_id: str) -> bool:
        tx = self._active_txs.get(tx_id)
        if not tx or tx.state != TransactionState.VERIFY:
            return False
        
        tx.state = TransactionState.COMMIT
        if self.state_manager:
            self.state_manager.execute("UPDATE _tx_journal SET state = ? WHERE tx_id = ?", (tx.state.value, tx_id))
            
        logger.debug(f"TX {tx_id[:8]} COMMITTED")
        self._active_txs.pop(tx_id, None)
        return True

    def rollback(self, tx_id: str, reason: str = "Unknown") -> bool:
        tx = self._active_txs.get(tx_id)
        if not tx:
            return False
            
        logger.warning(f"TX {tx_id[:8]} ROLLBACK triggered: {reason}")
        
        if tx.state == TransactionState.EXECUTE and tx.tx_type == TransactionType.IRREVERSIBLE:
            logger.error(f"Cannot rollback IRREVERSIBLE transaction {tx_id[:8]} that was already executing!")
            tx.state = TransactionState.TAINTED
            if self.state_manager:
                self.state_manager.execute("UPDATE _tx_journal SET state = ? WHERE tx_id = ?", (tx.state.value, tx_id))
            return False
            
        if tx.state in (TransactionState.EXECUTE, TransactionState.VERIFY):
            if tx.tx_type in (TransactionType.REVERSIBLE, TransactionType.COMPENSATABLE):
                # In a full system, invoke compensation logic here based on compensation_data
                logger.info(f"Applying compensation for TX {tx_id[:8]}")
        
        tx.state = TransactionState.ROLLBACK
        if self.state_manager:
            self.state_manager.execute("UPDATE _tx_journal SET state = ? WHERE tx_id = ?", (tx.state.value, tx_id))
            
        self._active_txs.pop(tx_id, None)
        return True

    def reconcile_crashes(self) -> List[TransactionRecord]:
        """
        Called on startup to find transactions that were in EXECUTE state during a crash.
        """
        # In a real DB, query for state == 'EXECUTE'
        # For now, memory mock
        crashed = [tx for tx in self._journal if tx.state == TransactionState.EXECUTE]
        for tx in crashed:
            logger.warning(f"Reconciling crashed TX {tx.tx_id[:8]} ({tx.tx_type.value})")
            if tx.tx_type == TransactionType.IRREVERSIBLE:
                tx.state = TransactionState.TAINTED
            else:
                self.rollback(tx.tx_id, "Mid-execution crash recovery")
        return crashed
