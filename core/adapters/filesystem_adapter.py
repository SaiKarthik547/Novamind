import os
import shutil
import logging
import hashlib
import uuid
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
        # Observation target for local verify()/reconcile(): the last write
        # this adapter instance performed (path + digest of final on-disk bytes).
        self._last_write: Optional[Dict[str, Any]] = None

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

        # Any new write attempt invalidates the previous observation target.
        self._last_write = None

        target = os.path.abspath(path)
        parent = os.path.dirname(target)
        if parent and not os.path.isdir(parent):
            return {"success": False, "error": f"Parent directory does not exist: {parent}"}

        if mode in ("w", "wt", "w+"):
            # Atomic replace: write a temp file in the SAME directory, flush+
            # fsync its contents, then os.replace() it over the target (atomic
            # on Windows via MoveFileEx). A crash leaves either the old file or
            # the new file — never a torn/partial one.
            tmp_path = f"{target}.{uuid.uuid4().hex}.tmp"
            try:
                with open(tmp_path, "w", encoding=encoding) as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, target)
            except BaseException:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                raise
        elif mode in ("a", "at", "a+", "at+"):
            # Append cannot be expressed as an atomic replace; durability is
            # still enforced with flush + fsync before returning.
            with open(target, mode, encoding=encoding) as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
        else:
            raise ValueError(
                f"Unsupported write mode {mode!r}. The canonical filesystem "
                f"lane only permits atomic replace ('w') or append ('a')."
            )

        # Observe the FINAL on-disk bytes (not the intended bytes) so the
        # digest reflects what actually landed on storage.
        with open(target, "rb") as f:
            final_bytes = f.read()
        digest = hashlib.sha256(final_bytes).hexdigest()
        self._last_write = {"path": target, "sha256": digest, "bytes": len(final_bytes)}
        return {
            "success": True,
            "path": target,
            "bytes_written": len(final_bytes),
            "sha256": digest,
            "mode": mode,
        }
        
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

    def _last_write_intact(self) -> bool:
        """True only if the last observed write is still present with identical bytes."""
        if not self._last_write:
            return False
        try:
            with open(self._last_write["path"], "rb") as f:
                observed = hashlib.sha256(f.read()).hexdigest()
            return observed == self._last_write["sha256"]
        except OSError:
            return False

    def verify(self, mode: VerificationMode) -> bool:
        """
        Adapter-local confirmation that the last write this adapter instance
        performed is still on disk with identical bytes (sha256 match).

        This is NOT the kernel's authoritative verification — the execution
        dispatcher performs independent post-dispatch observation before an
        intent may reach COMPLETED. Returns False when this adapter instance
        has no observed write to verify.
        """
        self._state = AdapterState.VERIFYING
        if not self._last_write:
            logger.warning("FilesystemAdapter.verify: no observed write to verify.")
            self._state = AdapterState.ATTACHED
            return False
        ok = self._last_write_intact()
        if not ok:
            logger.error(
                f"FilesystemAdapter.verify: on-disk state diverged for "
                f"{self._last_write['path']}"
            )
        self._state = AdapterState.ATTACHED
        return ok

    def reconcile(self) -> bool:
        """
        Re-check whether the last observed write is intact. The adapter does
        NOT retain the written content, so it cannot re-apply a lost write;
        it reports honestly: True when state already matches, False when the
        divergence cannot be repaired locally (kernel-side recovery owns that).
        """
        self._state = AdapterState.RECONCILING
        ok = self._last_write_intact()
        self._state = AdapterState.ATTACHED
        return ok

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