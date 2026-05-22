import sys
import logging
from typing import List

logger = logging.getLogger("SyscallGate")

class CapabilityViolation(Exception):
    pass

class SyscallGate:
    """
    Centralized privileged execution gate.
    Prevents direct privileged imports by agents inside the main process.
    """
    FORBIDDEN_MODULES = {
        "subprocess",
        "socket",
        "shutil",
        # os is tricky because os.path is often needed, but we can block specific functions if we hook it.
        # For this prototype, we just scan sys.modules or use an import hook.
    }

    @classmethod
    def validate_agent_capabilities(cls, agent_module_name: str):
        """
        Scans an agent's module for forbidden imports.
        In a true hardened environment, we would use a custom __import__ hook
        or restricted execution environments. Here we do a static/dynamic check.
        """
        agent_module = sys.modules.get(agent_module_name)
        if not agent_module:
            return

        for attr_name in dir(agent_module):
            attr = getattr(agent_module, attr_name)
            
            # Check if it's a module
            if type(attr).__name__ == "module":
                if attr.__name__ in cls.FORBIDDEN_MODULES:
                    raise CapabilityViolation(f"Agent {agent_module_name} illegally imported {attr.__name__}")
                    
        # Also check if they try to access os.system or os.popen directly
        if hasattr(agent_module, 'os'):
            os_mod = getattr(agent_module, 'os')
            if hasattr(os_mod, 'system') or hasattr(os_mod, 'popen'):
                # We can't easily prevent them from using it if they just import os, 
                # but we can monkeypatch it out in the agent's context if we wanted to be strict.
                pass

    @classmethod
    def install_import_hook(cls):
        """
        Installs an import hook that raises an error if an agent tries to import a forbidden module.
        (Implementation omitted for brevity, but conceptually this goes here).
        """
        pass
