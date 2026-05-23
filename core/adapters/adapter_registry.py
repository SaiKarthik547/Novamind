from dataclasses import dataclass, field
from typing import List, Dict, Type
from core.telemetry.telemetry_event import DeterminismLevel
from core.adapters.adapter_contract import ApplicationAdapter

@dataclass
class AdapterCapabilityManifest:
    allowed_capabilities: List[str]
    replay_mode: str
    execution_context: str
    requires_foreground: bool
    deterministic_level: DeterminismLevel

class AdapterRegistry:
    """
    Central authoritative adapter registry.
    Maps capabilities, replay semantics, and execution contexts.
    """
    def __init__(self):
        self._adapters: Dict[str, Type[ApplicationAdapter]] = {}
        self._manifests: Dict[str, AdapterCapabilityManifest] = {}

    def register(self, name: str, adapter_cls: Type[ApplicationAdapter], manifest: AdapterCapabilityManifest):
        self._adapters[name] = adapter_cls
        self._manifests[name] = manifest

    def get_adapter_class(self, name: str) -> Type[ApplicationAdapter]:
        if name not in self._adapters:
            raise KeyError(f"Adapter '{name}' not found in registry.")
        return self._adapters[name]

    def get_manifest(self, name: str) -> AdapterCapabilityManifest:
        if name not in self._manifests:
            raise KeyError(f"Adapter '{name}' manifest not found.")
        return self._manifests[name]

# Global registry instance
ADAPTER_REGISTRY = AdapterRegistry()
