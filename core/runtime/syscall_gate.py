"""
core/runtime/syscall_gate.py
Capability Policy Layer (formerly Import Sandbox).

This is a POLICY ENFORCEMENT layer, not a mathematically secure sandbox.
The true security boundary is the Windows Job Object + OS boundary.
(Note: ctypes escape is possible and acknowledged, but restricted by the OS layer).
"""

import sys
import logging
from typing import FrozenSet

from core.runtime.exceptions import ImportCapabilityViolation

logger = logging.getLogger(__name__)

# Essential modules needed for Python bootstrap, logging, IPC, and standard execution.
BOOTSTRAP_ALLOWLIST = {
    "sys", "os", "importlib", "builtins", "_thread", "threading",
    "time", "logging", "asyncio", "multiprocessing", "traceback",
    "json", "cbor2", "struct", "typing", "collections", "contextlib",
    "enum", "uuid", "abc", "ctypes", "wintypes", "datetime", "re",
    "encodings", "codecs", "io", "math", "random", "_weakref", "weakref",
    "copy", "hashlib", "hmac", "secrets", "types", "string", "warnings"
}

# Mapping of module names to the capability required to import them
CAPABILITY_GATES = {
    "socket": "network",
    "urllib": "network",
    "requests": "network",
    "http": "network",
    
    "subprocess": "process_spawn",
    "multiprocessing.popen_spawn_win32": "process_spawn",
    
    "shutil": "filesystem_write",
    "pathlib": "filesystem_read",
}


class CapabilityPolicyHook:
    """
    Intercepts imports to enforce the deterministic capability lease.
    """
    def __init__(self, capabilities: FrozenSet[str]):
        self.capabilities = capabilities
        self._allowed_prefixes = [
            "encodings.", "collections.", "importlib.", "asyncio.", 
            "json.", "cbor2.", "multiprocessing.", "logging.", "urllib.parse"
        ]
        
    def find_spec(self, fullname, path, target=None):
        # 1. Allow application internals
        if fullname.startswith("core.") or fullname.startswith("workers.") or fullname.startswith("agents."):
            return None # Pass to standard importer
            
        # 2. Allow bootstrap essentials and their submodules
        if fullname in BOOTSTRAP_ALLOWLIST:
            return None
            
        for prefix in self._allowed_prefixes:
            if fullname.startswith(prefix):
                return None
                
        # 3. Check capability gates
        root_module = fullname.split('.')[0]
        
        # Exact match
        required_cap = CAPABILITY_GATES.get(fullname)
        if not required_cap:
            # Fallback to root module
            required_cap = CAPABILITY_GATES.get(root_module)
            
        if required_cap and required_cap not in self.capabilities:
            logger.warning(f"Worker blocked from importing '{fullname}' (Requires capability: {required_cap})")
            raise ImportCapabilityViolation(
                f"Worker lacks '{required_cap}' capability required to import '{fullname}'."
            )

        # Allow everything else (this is a policy layer, not a paranoid sandbox)
        return None


def install_import_hook(capabilities: frozenset):
    """
    Installs the Capability Policy Layer for the current process.
    Capabilities must be a frozenset to ensure immutability post-handshake.
    """
    if not isinstance(capabilities, frozenset):
        raise TypeError("Capabilities must be a frozenset.")
        
    # Check if already installed
    for hook in sys.meta_path:
        if isinstance(hook, CapabilityPolicyHook):
            return
            
    sys.meta_path.insert(0, CapabilityPolicyHook(capabilities))
    logger.info(f"[SyscallGate] Policy Layer installed. Immutable Lease: {set(capabilities)}")
