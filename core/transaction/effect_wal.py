import os
import json
import struct
import hashlib
import threading
import logging
from typing import Dict, Any, List, Optional
from enum import Enum

logger = logging.getLogger("EffectWAL")

class WalState(Enum):
    PREPARE = "PREPARE"
    LEASE_BIND = "LEASE_BIND"
    DISPATCH = "DISPATCH"
    EXECUTE_BEGIN = "EXECUTE_BEGIN"
    EXECUTE_END = "EXECUTE_END"
    VERIFY = "VERIFY"
    COMMIT = "COMMIT"
    ROLLBACK = "ROLLBACK"


class WalCorruptionError(Exception):
    """Implementation stub"""


class EffectWal:
    """
    Durable Write-Ahead Log for side effects.
    Uses fsync barriers and cryptographic hash chaining for integrity.
    """
    def __init__(self, filepath: str):
        self.filepath = filepath
        self._lock = threading.Lock()
        
        self.global_seq = 0
        self.last_hash = hashlib.sha256(b"genesis").hexdigest()
        self._fd = None
        
        # In-memory indices for quick reconciliation
        self.transactions: Dict[str, List[Dict[str, Any]]] = {}
        
        self._open_and_recover()

    def _open_and_recover(self):
        with self._lock:
            if not os.path.exists(self.filepath):
                self._fd = open(self.filepath, "wb")
                return

            self._fd = open(self.filepath, "r+b")
            try:
                self._recover()
            except WalCorruptionError as e:
                logger.critical(f"WAL Corruption Detected: {e}")
                # A robust system would truncate at the last valid boundary
                # and quarantine. For this iteration, we raise.
                raise

    def _recover(self):
        """Reads WAL, verifies hash chain, rebuilds memory indices."""
        self._fd.seek(0)
        while True:
            # Read length prefix (4 bytes)
            len_bytes = self._fd.read(4)
            if not len_bytes:
                break # EOF
            if len(len_bytes) < 4:
                raise WalCorruptionError("Truncated WAL: incomplete length prefix")

            record_len = struct.unpack(">I", len_bytes)[0]
            
            # Read payload and hash (record_len + 64 bytes for SHA256 hex string)
            # Actually, let's embed hash inside the JSON or as a suffix. 
            # We'll use suffix for simpler framing: [4:len][payload][64:prev_hash]
            payload = self._fd.read(record_len)
            if len(payload) < record_len:
                raise WalCorruptionError(f"Truncated WAL: expected {record_len} payload bytes, got {len(payload)}")
                
            recorded_prev_hash = self._fd.read(64).decode('ascii')
            if len(recorded_prev_hash) < 64:
                raise WalCorruptionError("Truncated WAL: missing hash chain suffix")
                
            # Verify chain
            if recorded_prev_hash != self.last_hash:
                raise WalCorruptionError(f"Hash chain broken at seq {self.global_seq}. Expected prev {self.last_hash}, found {recorded_prev_hash}")
                
            data = json.loads(payload.decode('utf-8'))
            self.global_seq = data["global_seq"]
            
            # Calculate new hash
            self.last_hash = hashlib.sha256(self.last_hash.encode() + payload).hexdigest()
            
            # Update index
            tx_id = data.get("tx_id")
            if tx_id:
                if tx_id not in self.transactions:
                    self.transactions[tx_id] = []
                self.transactions[tx_id].append(data)

    def append(self, tx_id: str, state: WalState, payload: Dict[str, Any], worker_id: str = "") -> int:
        """
        Appends a record, writes to disk, and fsyncs.
        """
        with self._lock:
            self.global_seq += 1
            
            record = {
                "global_seq": self.global_seq,
                "tx_id": tx_id,
                "state": state.value,
                "worker_id": worker_id,
                "payload": payload
            }
            
            payload_bytes = json.dumps(record, sort_keys=True).encode('utf-8')
            record_len = len(payload_bytes)
            
            # Frame: [Length:4][Payload][PrevHash:64]
            frame = struct.pack(">I", record_len) + payload_bytes + self.last_hash.encode('ascii')
            
            self._fd.write(frame)
            self._fd.flush()
            os.fsync(self._fd.fileno()) # fsync barrier
            
            # Update chain
            self.last_hash = hashlib.sha256(self.last_hash.encode() + payload_bytes).hexdigest()
            
            if tx_id not in self.transactions:
                self.transactions[tx_id] = []
            self.transactions[tx_id].append(record)
            
            return self.global_seq

    def close(self):
        if self._fd:
            self._fd.close()
            self._fd = None