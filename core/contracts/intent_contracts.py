from typing import Dict, List
from dataclasses import dataclass
from core.execution.execution_intent import ExecutionIntent

@dataclass
class IntentSchemaContract:
    adapter_name: str
    operation: str
    required_payload_keys: List[str]
    allowed_payload_keys: List[str]
    idempotent: bool
    # L2-B: Kernel convergence classification
    determinism_class: str = "SEMI_DETERMINISTIC"   # DETERMINISTIC | SEMI_DETERMINISTIC | NON_DETERMINISTIC
    authority_origin: str = "legacy_bridge"          # 'kernel' | 'legacy_bridge' | 'unsafe_runtime'

class IntentContractRegistry:
    """
    Static registry for execution intents.
    Prevents adapters from acting as implicit, untyped runtime plugins.
    Ensures every intent is formally typed and validated before dispatch.
    """
    _contracts: Dict[str, Dict[str, IntentSchemaContract]] = {}

    @classmethod
    def register(
        cls,
        adapter_name: str,
        operation: str,
        required_keys: List[str],
        allowed_keys: List[str],
        idempotent: bool,
        determinism_class: str = "SEMI_DETERMINISTIC",
        authority_origin: str = "kernel",
    ):
        if adapter_name not in cls._contracts:
            cls._contracts[adapter_name] = {}

        cls._contracts[adapter_name][operation] = IntentSchemaContract(
            adapter_name=adapter_name,
            operation=operation,
            required_payload_keys=required_keys,
            allowed_payload_keys=allowed_keys,
            idempotent=idempotent,
            determinism_class=determinism_class,
            authority_origin=authority_origin,
        )

    @classmethod
    def validate_intent(cls, intent: ExecutionIntent) -> bool:
        """Validates that the intent strictly adheres to the registered contract."""
        # L2-B: Reject intents from unsafe_runtime authority — these bypass the kernel
        if getattr(intent, 'authority_origin', None) == "unsafe_runtime":
            raise ValueError(
                f"Intent authority_origin='unsafe_runtime' is REJECTED. "
                f"All intents must originate from 'kernel' or 'legacy_bridge'. "
                f"Intent: {intent.adapter}.{intent.operation} (id={intent.intent_id})"
            )

        if intent.adapter not in cls._contracts:
            raise ValueError(f"Unknown adapter targeted: {intent.adapter}")

        adapter_contracts = cls._contracts[intent.adapter]
        if intent.operation not in adapter_contracts:
            raise ValueError(f"Adapter '{intent.adapter}' does not support operation '{intent.operation}'")

        contract = adapter_contracts[intent.operation]

        # Validate idempotency declaration
        if intent.idempotent != contract.idempotent:
            raise ValueError(f"Intent idempotency ({intent.idempotent}) does not match contract ({contract.idempotent})")

        # Validate payload schema
        for req_key in contract.required_payload_keys:
            if req_key not in intent.payload:
                raise ValueError(f"Intent payload missing required key: '{req_key}'")

        for provided_key in intent.payload.keys():
            if provided_key not in contract.allowed_payload_keys and provided_key not in contract.required_payload_keys:
                raise ValueError(f"Intent payload contains unauthorized key: '{provided_key}'")

        return True

# --- Bootstrap Static Contracts ---
# ProcessAdapter  (SEMI_DETERMINISTIC — OS scheduler affects timing)
IntentContractRegistry.register("process", "spawn", ["cmd"], ["cwd", "env", "timeout"], idempotent=False,
                                determinism_class="SEMI_DETERMINISTIC", authority_origin="kernel")
IntentContractRegistry.register("process", "kill", ["pid"], ["force"], idempotent=True,
                                determinism_class="SEMI_DETERMINISTIC", authority_origin="kernel")

# FilesystemAdapter  (DETERMINISTIC — pure path operations)
IntentContractRegistry.register("filesystem", "read_file", ["path"], ["encoding"], idempotent=True,
                                determinism_class="DETERMINISTIC", authority_origin="kernel")
IntentContractRegistry.register("filesystem", "write_file", ["path", "content"], ["encoding", "append"], idempotent=False,
                                determinism_class="DETERMINISTIC", authority_origin="kernel")
IntentContractRegistry.register("filesystem", "mkdir", ["path"], ["parents", "exist_ok"], idempotent=True,
                                determinism_class="DETERMINISTIC", authority_origin="kernel")

# RegistryAdapter  (DETERMINISTIC — key-value store)
IntentContractRegistry.register("registry", "get_key", ["path", "key"], [], idempotent=True,
                                determinism_class="DETERMINISTIC", authority_origin="kernel")
IntentContractRegistry.register("registry", "set_key", ["path", "key", "value", "type"], [], idempotent=False,
                                determinism_class="DETERMINISTIC", authority_origin="kernel")

# NetworkAdapter  (SEMI_DETERMINISTIC — network I/O)
IntentContractRegistry.register("network", "http_get", ["url"], ["headers", "timeout"], idempotent=True,
                                determinism_class="SEMI_DETERMINISTIC", authority_origin="kernel")
IntentContractRegistry.register("network", "http_post", ["url", "body"], ["headers", "timeout"], idempotent=False,
                                determinism_class="SEMI_DETERMINISTIC", authority_origin="kernel")

# Legacy UI Quarantine  (NON_DETERMINISTIC — screen state is environmental)
IntentContractRegistry.register("legacy_ui", "click", ["x", "y"], ["button", "clicks"], idempotent=False,
                                determinism_class="NON_DETERMINISTIC", authority_origin="legacy_bridge")
IntentContractRegistry.register("legacy_ui", "type", ["text"], ["interval"], idempotent=False,
                                determinism_class="NON_DETERMINISTIC", authority_origin="legacy_bridge")
