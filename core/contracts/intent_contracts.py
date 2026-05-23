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

class IntentContractRegistry:
    """
    Static registry for execution intents.
    Prevents adapters from acting as implicit, untyped runtime plugins.
    Ensures every intent is formally typed and validated before dispatch.
    """
    _contracts: Dict[str, Dict[str, IntentSchemaContract]] = {}

    @classmethod
    def register(cls, adapter_name: str, operation: str, required_keys: List[str], allowed_keys: List[str], idempotent: bool):
        if adapter_name not in cls._contracts:
            cls._contracts[adapter_name] = {}
            
        cls._contracts[adapter_name][operation] = IntentSchemaContract(
            adapter_name=adapter_name,
            operation=operation,
            required_payload_keys=required_keys,
            allowed_payload_keys=allowed_keys,
            idempotent=idempotent
        )

    @classmethod
    def validate_intent(cls, intent: ExecutionIntent) -> bool:
        """Validates that the intent strictly adheres to the registered contract."""
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
# ProcessAdapter
IntentContractRegistry.register("process", "spawn", ["cmd"], ["cwd", "env", "timeout"], idempotent=False)
IntentContractRegistry.register("process", "kill", ["pid"], ["force"], idempotent=True)

# FilesystemAdapter
IntentContractRegistry.register("filesystem", "read_file", ["path"], ["encoding"], idempotent=True)
IntentContractRegistry.register("filesystem", "write_file", ["path", "content"], ["encoding", "append"], idempotent=False)
IntentContractRegistry.register("filesystem", "mkdir", ["path"], ["parents", "exist_ok"], idempotent=True)

# RegistryAdapter
IntentContractRegistry.register("registry", "get_key", ["path", "key"], [], idempotent=True)
IntentContractRegistry.register("registry", "set_key", ["path", "key", "value", "type"], [], idempotent=False)

# NetworkAdapter
IntentContractRegistry.register("network", "http_get", ["url"], ["headers", "timeout"], idempotent=True)
IntentContractRegistry.register("network", "http_post", ["url", "body"], ["headers", "timeout"], idempotent=False)

# Legacy UI Quarantine
IntentContractRegistry.register("legacy_ui", "click", ["x", "y"], ["button", "clicks"], idempotent=False)
IntentContractRegistry.register("legacy_ui", "type", ["text"], ["interval"], idempotent=False)
