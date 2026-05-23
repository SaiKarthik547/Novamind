import os
import shutil
import logging
from typing import Dict, Any, Optional

from core.adapters.adapter_contract import ApplicationAdapter, AdapterState, VerificationMode
from core.execution.execution_intent import ExecutionIntent
from core.telemetry.telemetry_event import DeterminismLevel
from core.adapters.adapter_registry import ADAPTER_REGISTRY, AdapterCapabilityManifest
from core.contracts.intent_contracts import IntentContractRegistry

logger = logging.getLogger("FilesystemAdapter")

# Register static contracts for Filesystem
IntentContractRegistry.register("filesystem", "read", ["path"], ["encoding"], True)
IntentContractRegistry.register("filesystem", "write", ["path", "content"], ["encoding", "mode"], False)
IntentContractRegistry.register("filesystem", "delete", ["path"], ["recursive"], True)
IntentContractRegistry.register("filesystem", "mkdir", ["path"], ["parents", "exist_ok"], True)

class FilesystemAdapter(ApplicationAdapter):
    """
    Deterministic subsystem for filesystem mutations.
    Enforces replay classification to maintain determinism.
    All operations are synchronous for now, utilizing standard library OS modules.
    """
    def __init__(self):
        self._state = AdapterState.CREATED
        self._determinism = DeterminismLevel.STRICT

    def get_state(self) -> AdapterState:
        return self._state

    def initialize(self) -> bool:
        self._state = AdapterState.INITIALIZING
        self._state = AdapterState.ATTACHED
        return True

    def attach(self) -> bool:
        self._state = AdapterState.ATTACHED
        return True

    def execute(self, intent: 'ExecutionIntent') -> Any:
        self._state = AdapterState.EXECUTING
        
        op = intent.operation
        payload = intent.payload
        
        try:
            if op == "read":
                result = self._do_read(payload)
            elif op == "write":
                result = self._do_write(payload)
            elif op == "delete":
                result = self._do_delete(payload)
            elif op == "mkdir":
                result = self._do_mkdir(payload)
            else:
                raise ValueError(f"Unknown operation: {op}")
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            self._state = AdapterState.ATTACHED
            return {"error": str(e), "success": False}

        self._state = AdapterState.ATTACHED
        return result

    def _do_read(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        path = payload["path"]
        encoding = payload.get("encoding", "utf-8")
        
        if not os.path.exists(path):
            return {"error": "File not found", "success": False}
            
        with open(path, "r", encoding=encoding) as f:
            content = f.read()
        return {"content": content, "success": True}

    def _do_write(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        path = payload["path"]
        content = payload["content"]
        encoding = payload.get("encoding", "utf-8")
        mode = payload.get("mode", "w")
        
        with open(path, mode, encoding=encoding) as f:
            f.write(content)
        return {"success": True}
        
    def _do_delete(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        path = payload["path"]
        recursive = payload.get("recursive", False)
        
        if not os.path.exists(path):
            return {"success": True} # Idempotent
            
        if os.path.isdir(path):
            if recursive:
                shutil.rmtree(path)
            else:
                os.rmdir(path)
        else:
            os.remove(path)
        return {"success": True}

    def _do_mkdir(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        path = payload["path"]
        parents = payload.get("parents", True)
        exist_ok = payload.get("exist_ok", True)
        
        os.makedirs(path, exist_ok=exist_ok)
        return {"success": True}

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

# Register Adapter
ADAPTER_REGISTRY.register(
    "filesystem", FilesystemAdapter,
    AdapterCapabilityManifest(
        allowed_capabilities=["read", "write", "delete", "mkdir"],
        replay_mode="STRUCTURAL",
        execution_context="BACKGROUND",
        requires_foreground=False,
        deterministic_level=DeterminismLevel.STRICT
    )
)