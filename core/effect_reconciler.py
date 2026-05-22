import logging
from enum import Enum
from typing import Dict, List, Any

from core.effect_wal import EffectWal, WalState

logger = logging.getLogger("EffectReconciler")


class ReconciliationState(Enum):
    SAFE_REPLAY = "SAFE_REPLAY"
    COMPENSATE = "COMPENSATE"
    TAINT = "TAINT"
    MANUAL_INTERVENTION = "MANUAL_INTERVENTION"
    UNKNOWN_EFFECT_STATE = "UNKNOWN_EFFECT_STATE"
    EXTERNAL_STATE_DIVERGED = "EXTERNAL_STATE_DIVERGED"
    DUPLICATE_RISK = "DUPLICATE_RISK"
    COMPENSATION_REQUIRED = "COMPENSATION_REQUIRED"


class EffectReconciler:
    """
    Analyzes the WAL on boot to determine crash-state semantics and 
    authoritative reconciliation strategies for incomplete transactions.
    """
    def __init__(self, wal: EffectWal):
        self.wal = wal

    def analyze(self) -> Dict[str, ReconciliationState]:
        """
        Scans all transactions in the WAL and assigns a reconciliation state to any
        that are incomplete (i.e. missing COMMIT or ROLLBACK).
        """
        results = {}
        for tx_id, records in self.wal.transactions.items():
            states = [WalState(r["state"]) for r in records]
            
            if WalState.COMMIT in states or WalState.ROLLBACK in states:
                continue # Transaction was cleanly finalized
                
            # Analyze incomplete transactions
            if WalState.VERIFY in states:
                # We finished execution and verification, but crashed before COMMIT
                results[tx_id] = ReconciliationState.SAFE_REPLAY
            
            elif WalState.EXECUTE_END in states:
                # We finished execution but crashed during verification
                results[tx_id] = ReconciliationState.EXTERNAL_STATE_DIVERGED
                
            elif WalState.EXECUTE_BEGIN in states:
                # We crashed WHILE executing the effect
                # This is the hardest state: we don't know if the OS finished it
                results[tx_id] = ReconciliationState.UNKNOWN_EFFECT_STATE
                
            elif WalState.DISPATCH in states:
                # Dispatched to worker, but worker never replied with EXECUTE_BEGIN
                # There is a risk the worker actually started it just as we crashed
                results[tx_id] = ReconciliationState.DUPLICATE_RISK
                
            else:
                # PREPARE or LEASE_BIND, but never dispatched
                results[tx_id] = ReconciliationState.SAFE_REPLAY
                
        # Second pass: classify based on capability reversibility
        for tx_id, rec_state in results.items():
            # If it's a known irreversible effect in an unknown state, we must escalate
            records = self.wal.transactions[tx_id]
            
            is_reversible = True
            for r in records:
                if "is_reversible" in r.get("payload", {}):
                    is_reversible = r["payload"]["is_reversible"]
            
            if not is_reversible and rec_state in (ReconciliationState.UNKNOWN_EFFECT_STATE, ReconciliationState.DUPLICATE_RISK):
                results[tx_id] = ReconciliationState.MANUAL_INTERVENTION
                logger.critical(f"Transaction {tx_id} requires MANUAL_INTERVENTION: irreversible effect in unknown state.")
            elif not is_reversible and rec_state == ReconciliationState.EXTERNAL_STATE_DIVERGED:
                results[tx_id] = ReconciliationState.COMPENSATION_REQUIRED
                
        return results
