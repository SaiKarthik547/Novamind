"""
core/adapters/system_lane.py

Step 9 Addendum: Multi-Lane Adapter for OS Execution
Authoritative execution lane for handling raw OS subprocesses and scripts.
Receives ExecutionEvents from the Orchestrator and performs actual execution,
keeping the Semantic Agent pure.
"""

import logging
import os
import subprocess
import tempfile
import sys
import shutil
import time
from typing import Dict, Any, Optional

logger = logging.getLogger("SystemLane")

class SystemExecutionLane:
    """
    Authoritative Execution Lane for OS-level subprocess and script dispatch.
    Agents yield PENDING intents; the ExecutionScheduler routes them here.
    """

    MAX_EXECUTION_TIME = 300

    def execute_intent(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Routes the intent payload to the specific execution mechanic.
        """
        if action == "system_command":
            return self._execute_command(payload)
        elif action == "execute_script":
            return self._execute_script(payload)
        else:
            logger.error(f"[SystemLane] Unsupported action: {action}")
            return {"success": False, "error": f"Unsupported action: {action}"}

    def _execute_command(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        command = payload.get("command")
        shell = payload.get("shell", True)
        cwd = payload.get("cwd")
        timeout = payload.get("timeout", self.MAX_EXECUTION_TIME)
        
        run_env = os.environ.copy()
        
        start = time.monotonic()
        try:
            proc = subprocess.Popen(
                command, shell=shell, cwd=cwd, env=run_env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace"
            )
            
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
                elapsed = time.monotonic() - start
                return {
                    "success": proc.returncode == 0,
                    "returncode": proc.returncode,
                    "stdout": (stdout or "")[:50000],
                    "stderr": (stderr or "")[:10000],
                    "execution_time": round(elapsed, 2),
                    "pid": proc.pid,
                }
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                return {
                    "success": False,
                    "error": f"Command timed out after {timeout}s",
                    "stdout": "", "stderr": "TIMEOUT",
                }
        except Exception as e:
            logger.debug(f"[SystemLane] Exception caught: {e}")
            return {"success": False, "error": str(e)}

    def _execute_script(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        code = payload.get("code")
        language = payload.get("language", "python")
        timeout = payload.get("timeout", 60)
        
        if language == "python":
            suffix = ".py"
            cmd = [sys.executable]
        elif language in ("bash", "sh"):
            suffix = ".sh"
            cmd = [shutil.which("bash") or shutil.which("sh") or "sh"]
        elif language == "javascript":
            suffix = ".js"
            node = shutil.which("node") or shutil.which("nodejs")
            if not node:
                return {"success": False, "error": "Node.js not found"}
            cmd = [node]
        elif language in ("powershell", "ps1"):
            suffix = ".ps1"
            ps = shutil.which("pwsh") or shutil.which("powershell")
            if not ps:
                return {"success": False, "error": "PowerShell not found"}
            cmd = [ps, "-ExecutionPolicy", "Bypass", "-NonInteractive", "-File"]
        elif language in ("cmd", "batch"):
            suffix = ".bat"
            cmd = ["cmd.exe", "/C"] if os.name == "nt" else ["sh"]
        else:
            return {"success": False, "error": f"Unsupported language: {language}"}

        with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8") as f:
            f.write(code)
            tmp = f.name
            
        cmd.append(tmp)
        
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace"
            )
            try:
                out, err = proc.communicate(timeout=timeout)
                return {
                    "success": proc.returncode == 0,
                    "returncode": proc.returncode,
                    "stdout": (out or "")[:50000],
                    "stderr": (err or "")[:10000],
                }
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                return {"success": False, "error": f"Script timed out after {timeout}s"}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            try:
                os.unlink(tmp)
            except Exception as e:
                logger.debug(f"[SystemLane] Cleanup error: {e}")
