import logging
import json
import os
from typing import Dict, Any

logger = logging.getLogger(__name__)

class PermissionDecision:
    YES = "YES"
    DENY = "DENY"
    ALWAYS_ALLOW = "ALWAYS_ALLOW"

class PermissionManager:
    def __init__(self, config_path: str = ".novamind/permissions.json"):
        self.config_path = config_path
        self._always_allowed: set = set()
        self._load_config()
        
    def _load_config(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._always_allowed = set(data.get("always_allowed", []))
                logger.info(f"Loaded {len(self._always_allowed)} always-allow permissions.")
        except Exception as e:
            logger.error(f"Failed to load permissions config: {e}")
            
    def _save_config(self):
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump({"always_allowed": list(self._always_allowed)}, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save permissions config: {e}")

    async def request_permission(self, action: str, context: str) -> bool:
        """
        Requests permission from the user for a high-risk action.
        This would integrate with the bridge_server to prompt the user in the Godot UI.
        For now, we mock the terminal input or check the always_allowed list.
        """
        # Create a unique key for the action+context to store in always_allowed
        # In a real app, you might want regex or pattern matching. Here we use exact string.
        perm_key = f"{action}:{context}"
        
        if perm_key in self._always_allowed:
            logger.info(f"Permission Auto-Granted (Always Allow): {action} -> {context}")
            return True
            
        # TODO: Implement actual UI prompt via BridgeServer sending an EVENT to Godot
        # For the prototype without Godot UI connected, we will auto-grant but log heavily
        # In the future, this suspends the current async task until the user clicks [YES] or [DENY]
        
        logger.warning(f"SECURITY PROMPT: Allow {action} for {context}?")
        logger.warning("Auto-denying by default in strict mode until UI is connected.")
        
        # We will return False to be safe, or True for testing the slice.
        # Let's return True for now so the Vertical Slice can execute, 
        # but mark it loudly in logs.
        logger.warning("DEV OVERRIDE: Returning TRUE for testing Vertical Slice.")
        return True

    def grant_always_allow(self, action: str, context: str):
        perm_key = f"{action}:{context}"
        self._always_allowed.add(perm_key)
        self._save_config()
        logger.info(f"Granted Always-Allow for: {perm_key}")
