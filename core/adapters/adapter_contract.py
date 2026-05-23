from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, Any

class AdapterState(Enum):
    CREATED = "CREATED"
    INITIALIZING = "INITIALIZING"
    ATTACHED = "ATTACHED"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    RECONCILING = "RECONCILING"
    DEGRADED = "DEGRADED"
    TERMINATED = "TERMINATED"

class VerificationMode(Enum):
    STRUCTURAL = "STRUCTURAL"  # API succeeded
    SEMANTIC = "SEMANTIC"      # Expected state achieved (e.g. DOM updated)
    VISUAL = "VISUAL"          # Pixels changed as expected
    REPLAY = "REPLAY"          # Deterministic replay lineage verified

class ApplicationAdapter(ABC):
    """
    The fundamental contract for all deterministic execution endpoints.
    Direct application control (e.g., PyAutoGUI, raw OS execution) is strictly prohibited
    outside of supervised Adapters.
    """
    
    @abstractmethod
    def get_state(self) -> AdapterState:
        raise NotImplementedError()

    @abstractmethod
    def initialize(self) -> bool:
        """Allocate resources and prepare the runtime context."""
        raise NotImplementedError()

    @abstractmethod
    def attach(self) -> bool:
        """Bind to the target process or abstraction (e.g., CDP port, PTY)."""
        raise NotImplementedError()

    @abstractmethod
    def execute(self, intent: 'ExecutionIntent') -> Any:
        """Execute a deterministic operation based on the intent."""
        raise NotImplementedError()

    @abstractmethod
    def verify(self, mode: VerificationMode) -> bool:
        """Ensure the side effects of execution match expectations."""
        raise NotImplementedError()

    @abstractmethod
    def reconcile(self) -> bool:
        """Attempt recovery if verification fails or state diverges."""
        raise NotImplementedError()

    @abstractmethod
    def teardown(self) -> None:
        """Deterministically release resources and unlink."""
        raise NotImplementedError()
