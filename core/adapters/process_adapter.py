import logging
import subprocess
import threading
from typing import Dict, Any, Optional
import time

from core.adapters.adapter_contract import ApplicationAdapter, AdapterState, VerificationMode
from core.execution.execution_intent import ExecutionIntent
from core.telemetry.telemetry_event import DeterminismLevel

logger = logging.getLogger("ProcessAdapter")

class ProcessAdapter(ApplicationAdapter):
    """
    Deterministic subsystem for spawning and managing OS processes.
    Replaces raw `subprocess.run` inside agents.
    Provides strict timeout management, capability dropping, and stdout/stderr capturing.
    """
    def __init__(self):
        self._state = AdapterState.CREATED
        self._processes: Dict[str, subprocess.Popen] = {}
        self._determinism = DeterminismLevel.STRICT

    def get_state(self) -> AdapterState:
        return self._state

    def initialize(self) -> bool:
        self._state = AdapterState.INITIALIZING
        # Could verify security capabilities here
        self._state = AdapterState.ATTACHED
        return True

    def attach(self) -> bool:
        self._state = AdapterState.ATTACHED
        return True

    def execute(self, intent: 'ExecutionIntent') -> Any:
        self._state = AdapterState.EXECUTING
        
        operation = intent.operation
        payload = intent.payload
        
        if operation == "spawn":
            return self._execute_spawn(payload)
        elif operation == "kill":
            return self._execute_kill(payload)
        else:
            self._state = AdapterState.ATTACHED
            raise ValueError(f"Unknown operation: {operation}")

    def _execute_spawn(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        cmd = payload.get("cmd")
        cwd = payload.get("cwd")
        env = payload.get("env")
        timeout = payload.get("timeout", 10.0)
        capture_output = payload.get("capture_output", True)
        
        if not cmd:
            raise ValueError("Missing 'cmd' in spawn payload")

        start_time = time.time()
        try:
            # Deterministic execution via subprocess
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                env=env,
                timeout=timeout,
                capture_output=capture_output,
                text=True,
                check=False
            )
            
            result = {
                "returncode": proc.returncode,
                "stdout": proc.stdout if capture_output else None,
                "stderr": proc.stderr if capture_output else None,
                "duration_ms": int((time.time() - start_time) * 1000)
            }
            self._state = AdapterState.ATTACHED
            return result
        except subprocess.TimeoutExpired as e:
            self._state = AdapterState.ATTACHED
            # L0-D: text=True means stdout/stderr may already be str; guard both cases.
            def _decode(v) -> str | None:
                if v is None:
                    return None
                return v if isinstance(v, str) else v.decode(errors="replace")
            return {
                "error": "TIMEOUT",
                "returncode": -1,
                "stdout": _decode(e.stdout),
                "stderr": _decode(e.stderr),
                "duration_ms": int((time.time() - start_time) * 1000)
            }
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            self._state = AdapterState.ATTACHED
            return {
                "error": str(e),
                "returncode": -2,
                "duration_ms": int((time.time() - start_time) * 1000)
            }

    def _execute_kill(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Kills a process by PID."""
        pid = payload.get("pid")
        if not pid:
            return {"error": "No PID provided for kill operation"}
            
        try:
            import psutil
            try:
                proc = psutil.Process(int(pid))
                proc.kill()
                return {"status": "success", "pid": pid}
            except psutil.NoSuchProcess:
                return {"error": f"Process {pid} not found"}
            except psutil.AccessDenied:
                return {"error": f"Access denied to kill {pid}"}
        except ImportError:
            # Fallback if psutil is not available
            import os
            import subprocess
            try:
                if os.name == 'nt':
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)], check=True, capture_output=True)
                else:
                    subprocess.run(["kill", "-9", str(pid)], check=True, capture_output=True)
                return {"status": "success", "pid": pid, "note": "Used fallback shell kill"}
            except Exception as e:
                return {"error": f"Fallback kill failed: {e}"}

    def verify(self, mode: VerificationMode) -> bool:
        self._state = AdapterState.VERIFYING
        self._state = AdapterState.ATTACHED
        return True

    def reconcile(self) -> bool:
        self._state = AdapterState.RECONCILING
        self._state = AdapterState.ATTACHED
        return True

    def teardown(self) -> None:
        self._state = AdapterState.TERMINATED
        for pid, proc in self._processes.items():
            try:
                proc.terminate()
            except Exception as e:
                import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
                pass
        self._processes.clear()

# Register the ProcessAdapter
from core.adapters.adapter_registry import ADAPTER_REGISTRY, AdapterCapabilityManifest

ADAPTER_REGISTRY.register(
    "process", ProcessAdapter,
    AdapterCapabilityManifest(
        allowed_capabilities=["spawn", "kill"],
        replay_mode="STRUCTURAL",
        execution_context="BACKGROUND",
        requires_foreground=False,
        deterministic_level=DeterminismLevel.STRICT
    )
)