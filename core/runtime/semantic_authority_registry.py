"""
Semantic Authority Registry — Enforces the Semantic Ownership Law.

No mutable architectural domain may have more than one registered owner.
Shadow authorities, duplicate ownership, and cyclic ownership are explicitly banned.
"""
from typing import Dict, Type, Set, Any
import logging

logger = logging.getLogger("SemanticAuthorityRegistry")

class SemanticOwnershipViolation(Exception):
    """Raised when the Semantic Ownership Law is violated."""
    pass

class SemanticAuthorityRegistry:
    """
    Central registry for semantic runtime authority ownership.
    Used by tests, audits, and runtime assertions to formally verify topology.
    """
    _instance = None
    _owners: Dict[str, Any] = {}
    _lock = __import__("threading").RLock()
    _frozen: bool = False
    _topology_generation_hash: str = ""
    _epoch_id: str = ""

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._owners = {}
                    cls._frozen = False
                    cls._topology_generation_hash = ""
                    import uuid
                    cls._epoch_id = str(uuid.uuid4())
        return cls._instance

    @classmethod
    def register(cls, domain: str, authority: Any) -> None:
        """
        Formally registers a class or module as the singular authority over a given domain.
        """
        registry = cls()
        with cls._lock:
            if registry._frozen:
                raise SemanticOwnershipViolation(
                    f"Semantic Ownership Law Violation! Topology is frozen. Cannot register domain '{domain}'."
                )
                
            if domain in registry._owners:
                existing = registry._owners[domain]
                if existing is not authority:
                    name = getattr(authority, "__name__", str(authority))
                    existing_name = getattr(existing, "__name__", str(existing))
                    raise SemanticOwnershipViolation(
                        f"Semantic Ownership Law Violation! Domain '{domain}' is already owned by {existing_name}. "
                        f"Cannot register {name}."
                    )
            registry._owners[domain] = authority
            
        name = getattr(authority, "__name__", str(authority))
        logger.debug(f"Registered Authority: {name} owns domain '{domain}'")

    @classmethod
    def freeze_topology(cls) -> str:
        """
        Locks the topology. No further runtime authority assignments can be made.
        Returns the generation hash of the topology.
        """
        import hashlib
        import json
        registry = cls()
        with cls._lock:
            if registry._frozen:
                return registry._topology_generation_hash
                
            registry._frozen = True
            
            # Compute stable hash
            sorted_owners = {d: getattr(registry._owners[d], "__name__", str(registry._owners[d])) for d in sorted(registry._owners.keys())}
            hash_input = json.dumps(sorted_owners, sort_keys=True).encode("utf-8")
            registry._topology_generation_hash = hashlib.sha256(hash_input).hexdigest()
            logger.info(f"Topology Frozen. Generation Hash: {registry._topology_generation_hash}")
            return registry._topology_generation_hash
            
    @classmethod
    def get_topology_hash(cls) -> str:
        registry = cls()
        with cls._lock:
            if not registry._frozen:
                raise RuntimeError("Topology not frozen yet.")
            return registry._topology_generation_hash
            
    @classmethod
    def get_epoch_id(cls) -> str:
        return cls()._epoch_id

    @classmethod
    def get_owner(cls, domain: str) -> Any:
        """Returns the registered authority for a domain."""
        registry = cls()
        with cls._lock:
            if domain not in registry._owners:
                raise SemanticOwnershipViolation(f"Domain '{domain}' has no registered owner.")
            return registry._owners[domain]

    @classmethod
    def verify_ownership(cls, domain: str, claimant: Any) -> bool:
        """Checks if a claimant actually owns the domain."""
        try:
            return cls.get_owner(domain) is claimant
        except SemanticOwnershipViolation:
            return False

    @classmethod
    def snapshot(cls) -> Dict[str, Any]:
        """Returns a snapshot of the current ownership topology."""
        registry = cls()
        with cls._lock:
            snap = {
                domain: getattr(auth, "__name__", str(auth)) 
                for domain, auth in registry._owners.items()
            }
            return {
                "epoch_id": registry._epoch_id,
                "frozen": registry._frozen,
                "generation_hash": registry._topology_generation_hash,
                "domains": snap
            }

    @classmethod
    def clear_for_testing(cls) -> None:
        """Testing utility to clear the registry."""
        registry = cls()
        with cls._lock:
            registry._owners.clear()
            registry._frozen = False
            registry._topology_generation_hash = ""
            import uuid
            registry._epoch_id = str(uuid.uuid4())
