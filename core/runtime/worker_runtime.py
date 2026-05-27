import logging
import subprocess
import threading
import time
import uuid
import json
import sys
from typing import Dict, Optional, Callable

from core.ipc.worker_protocol import WorkerState, FrameType, WorkerIdentity, IpcFrame
from core.runtime.worker_sandbox import WorkerSandbox, JobAssignmentError
from core.contracts.runtime_events import WorkerDeathReason, EventType

logger = logging.getLogger("WorkerSupervisor")

HEARTBEAT_INTERVAL = 5.0
HEARTBEAT_TIMEOUT = 15.0

class WorkerSupervisor:
    """
    Supervises a single isolated worker process.
    Maintains the FSM, IPC channel, Job Object Sandbox, and Health Watchdog.
    """
    def __init__(self, worker_cmd: list[str], identity: WorkerIdentity, profile_name: str = "compute"):
        self.worker_cmd = worker_cmd
        self.identity = identity
        self.state = WorkerState.BOOTING
        self.death_reason = WorkerDeathReason.UNKNOWN
        
        self.process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._seq_num = 0
        
        # OS-level Containment Boundary
        self.sandbox = WorkerSandbox(
            name=identity.worker_id[:8],
            profile_name=profile_name,
            max_memory_mb=256 if profile_name == "compute" else 2048,
            cpu_limit_pct=20
        )
        
        # IPC Queues/Callbacks
        self.on_message: Optional[Callable[[IpcFrame], None]] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._watchdog_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # Heartbeat ownership
        self._last_heartbeat_ack_time = time.time()

    def _emit_wal_event(self, event_type: str, details: dict):
        """Write-Ahead Log event emission using RecoveryJournal."""
        logger.info(f"[WAL] {event_type} | {details}")
        
        # We synthesize an IntentExecutionState to log this lifecycle event.
        # Worker lifecycle events don't strictly have an intent_id, so we use the worker_id.
        try:
            from core.execution.recovery_journal import RecoveryJournal
            from core.execution.intent_execution_state import IntentExecutionState
            journal = RecoveryJournal.get_instance()
            
            # Map EventType to closest IntentExecutionState if applicable,
            # or use a generic state (like DISPATCHED/COMPLETED)
            state_val = IntentExecutionState.DISPATCHED
            if event_type == EventType.WORKER_KILLED:
                state_val = IntentExecutionState.TERMINATED
                
            journal.log_transition(
                intent_id=self.identity.worker_id,
                state=state_val,
                payload={"event_type": event_type, "details": details}
            )
        except Exception as e:
            logger.error(f"Failed to write WAL event for {self.identity.worker_id}: {e}")

    def start(self):
        with self._lock:
            if self.state != WorkerState.BOOTING:
                return

            logger.info(f"Starting worker {self.identity.worker_id}...")
            self._emit_wal_event(EventType.WORKER_STARTED, {"worker_id": self.identity.worker_id})
            
            try:
                # 1. Spawn Process
                self.process = subprocess.Popen(
                    self.worker_cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1
                )
            except Exception as e:
                logger.error(f"Failed to spawn worker process: {e}")
                self.death_reason = WorkerDeathReason.UNHANDLED_EXCEPTION
                self.state = WorkerState.DEAD
                return

            # 2. Assign Job Object (Commit to OS Sandbox)
            try:
                self.sandbox.assign_process(self.process.pid)
                self._emit_wal_event(EventType.WORKER_BOUND, {"worker_id": self.identity.worker_id, "pid": self.process.pid})
            except JobAssignmentError as e:
                logger.error(f"Job Object assignment failed: {e}. ROLLING BACK SPAWN.")
                self.process.kill()
                self.death_reason = WorkerDeathReason.CAPABILITY_VIOLATION
                self.state = WorkerState.DEAD
                self._emit_wal_event(EventType.WORKER_KILLED, {"worker_id": self.identity.worker_id, "reason": "JobAssignmentError"})
                return

            # 3. Initialize IPC & Watchdog
            self._last_heartbeat_ack_time = time.time()
            self._monitor_thread = threading.Thread(
                target=self._io_loop,
                daemon=True,
                name=f"WorkerIO-{self.identity.worker_id[:8]}"
            )
            self._watchdog_thread = threading.Thread(
                target=self._watchdog_loop,
                daemon=True,
                name=f"WorkerWD-{self.identity.worker_id[:8]}"
            )
            self._monitor_thread.start()
            self._watchdog_thread.start()
            
            # Send Handshake SYN + Capability Lease
            # In a real environment, capabilities are frozen here.
            self.send_frame(FrameType.HANDSHAKE_SYN, {
                "nonce": self.identity.supervisor_nonce,
                "capabilities": ["compute", "process_spawn"]
            })

    def stop(self, reason: WorkerDeathReason = WorkerDeathReason.SUPERVISOR_TERMINATED):
        with self._lock:
            if self.state in (WorkerState.DEAD, WorkerState.TERMINATING):
                return
            self.state = WorkerState.TERMINATING
            self.death_reason = reason
            self._stop_event.set()
            
            if self.process:
                self.send_frame(FrameType.TERMINATE, {"reason": reason.value})
                try:
                    self.process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    logger.warning(f"Worker {self.identity.worker_id} hung. Killing via Sandbox.")
                finally:
                    # Sandbox close guarantees OS-level termination of process and any children
                    self.sandbox.close()
                    # IPC Cleanup
                    if self.process.stdin: self.process.stdin.close()
                    if self.process.stdout: self.process.stdout.close()
                    if self.process.stderr: self.process.stderr.close()
                    
            self.state = WorkerState.DEAD
            self._emit_wal_event(EventType.WORKER_KILLED, {
                "worker_id": self.identity.worker_id, 
                "reason": self.death_reason.value
            })

    def _watchdog_loop(self):
        """KernelSupervisor explicitly owns heartbeat."""
        while not self._stop_event.is_set() and self.state not in (WorkerState.DEAD, WorkerState.TERMINATING):
            now = time.time()
            if now - self._last_heartbeat_ack_time > HEARTBEAT_TIMEOUT:
                logger.error(f"Worker {self.identity.worker_id} Heartbeat Timeout! Killing.")
                self.stop(reason=WorkerDeathReason.IPC_TIMEOUT)
                break
                
            self.send_frame(FrameType.HEARTBEAT, {"timestamp": now})
            time.sleep(HEARTBEAT_INTERVAL)

    def _io_loop(self):
        while not self._stop_event.is_set() and self.process and self.process.stdout:
            try:
                line = self.process.stdout.readline()
                if not line:
                    break # EOF (Process died or IPC closed)
                
                try:
                    data = json.loads(line)
                    self._handle_incoming(data)
                except json.JSONDecodeError:
                    logger.error(f"Worker {self.identity.worker_id} sent invalid JSON: {line.strip()}")
            except Exception as e:
                logger.error(f"Worker {self.identity.worker_id} IPC read error: {e}")
                break
                
        # If we exit the loop and we didn't call stop(), the worker died unexpectedly.
        if not self._stop_event.is_set():
            logger.error(f"Worker {self.identity.worker_id} died unexpectedly.")
            # We don't know the exact reason (memory limit, exception, etc) unless we query the OS.
            # For now, mark UNHANDLED_EXCEPTION and stop cleanly.
            self.stop(reason=WorkerDeathReason.UNHANDLED_EXCEPTION)

    def _handle_incoming(self, data: dict):
        try:
            frame_type = FrameType(data["type"])
            if frame_type == FrameType.HANDSHAKE_ACK:
                with self._lock:
                    self.state = WorkerState.READY
                    self._last_heartbeat_ack_time = time.time()
                    logger.info(f"Worker {self.identity.worker_id} READY.")
            elif frame_type == FrameType.HEARTBEAT: # Ack from worker
                self._last_heartbeat_ack_time = time.time()
            elif frame_type == FrameType.WORKER_PANIC:
                with self._lock:
                    self.state = WorkerState.DEGRADED
                    logger.critical(f"Worker {self.identity.worker_id} PANIC: {data.get('payload')}")
            
            if self.on_message:
                frame = IpcFrame(
                    seq_num=data.get("seq_num", 0),
                    type=frame_type,
                    identity=self.identity,
                    payload=data.get("payload", {}),
                    timestamp=data.get("timestamp", time.time()),
                    correlation_id=data.get("correlation_id", "")
                )
                self.on_message(frame)
        except Exception as e:
            logger.error(f"Error handling frame: {e}")

    def send_frame(self, frame_type: FrameType, payload: dict, correlation_id: str = ""):
        with self._lock:
            self._seq_num += 1
            frame = IpcFrame(
                seq_num=self._seq_num,
                type=frame_type,
                identity=self.identity,
                payload=payload,
                correlation_id=correlation_id
            )
            data_str = json.dumps(frame.dict()) + "\n"
            if self.process and self.process.stdin:
                try:
                    self.process.stdin.write(data_str)
                    self.process.stdin.flush()
                except Exception as e:
                    if not self._stop_event.is_set():
                        logger.error(f"Failed to send to worker {self.identity.worker_id}: {e}")
                        self.state = WorkerState.DEGRADED
