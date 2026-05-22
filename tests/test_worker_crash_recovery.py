import pytest
import os
from core.transaction.effect_wal import EffectWal, WalState, WalCorruptionError
from core.transaction.effect_reconciler import EffectReconciler, ReconciliationState

def test_wal_reconciliation_safe_replay():
    wal_path = "test_safe_replay.wal"
    if os.path.exists(wal_path): os.remove(wal_path)
    
    wal = EffectWal(wal_path)
    tx_id = "tx-123"
    wal.append(tx_id, WalState.PREPARE, {})
    wal.append(tx_id, WalState.LEASE_BIND, {})
    wal.append(tx_id, WalState.DISPATCH, {})
    wal.append(tx_id, WalState.EXECUTE_BEGIN, {})
    wal.append(tx_id, WalState.EXECUTE_END, {})
    wal.append(tx_id, WalState.VERIFY, {})
    # Crashed before COMMIT
    
    reconciler = EffectReconciler(wal)
    states = reconciler.analyze()
    
    assert states[tx_id] == ReconciliationState.SAFE_REPLAY
    
    wal.close()
    os.remove(wal_path)

def test_wal_reconciliation_unknown_state():
    wal_path = "test_unknown_state.wal"
    if os.path.exists(wal_path): os.remove(wal_path)
    
    wal = EffectWal(wal_path)
    tx_id = "tx-456"
    wal.append(tx_id, WalState.PREPARE, {"is_reversible": False})
    wal.append(tx_id, WalState.DISPATCH, {})
    wal.append(tx_id, WalState.EXECUTE_BEGIN, {})
    # Crashed DURING execution of irreversible effect
    
    reconciler = EffectReconciler(wal)
    states = reconciler.analyze()
    
    assert states[tx_id] == ReconciliationState.MANUAL_INTERVENTION
    
    wal.close()
    os.remove(wal_path)

def test_wal_corruption_detection():
    wal_path = "test_corruption.wal"
    if os.path.exists(wal_path): os.remove(wal_path)
    
    wal = EffectWal(wal_path)
    wal.append("tx-789", WalState.PREPARE, {})
    wal.close()
    
    # Tamper with the WAL
    with open(wal_path, "r+b") as f:
        f.seek(-10, os.SEEK_END)
        f.write(b"0000000000")
        
    with pytest.raises(WalCorruptionError):
        EffectWal(wal_path)
        
    os.remove(wal_path)
