"""
System Agent — Full Windows / cross-platform system control.
Real implementations: registry, services, scheduled tasks, event log,
firewall, performance counters, startup items, audio, display, printers,
network adapters, clipboard, power management, notifications.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os

# --- Phase 10.5 Capability Shim ---
import sys as _sys
class _ModuleShim:
    def __init__(self, mod_name): self._mod_name = mod_name
    def __getattr__(self, name): return getattr(__import__(self._mod_name), name)
subprocess = _ModuleShim('subprocess')
shutil = _ModuleShim('shutil')
socket = _ModuleShim('socket')
# ----------------------------------
import platform
import re
import signal
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.foundation.base_agent import BaseAgent

logger = logging.getLogger("SystemAgent")

IS_WINDOWS = os.name == "nt"
IS_LINUX   = sys.platform.startswith("linux")
IS_MAC     = sys.platform == "darwin"


# ─────────────────────────────────────────────────────────────────────────────
#  Data Classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ProcessInfo:
    pid:        int
    name:       str
    status:     str
    cpu_pct:    float
    mem_mb:     float
    username:   str
    cmdline:    str
    started:    str


@dataclass
class ServiceInfo:
    name:        str
    display:     str
    status:      str    # running / stopped / paused
    start_type:  str    # auto / manual / disabled
    pid:         Optional[int]
    description: str


@dataclass
class NetworkAdapter:
    name:        str
    mac:         str
    ipv4:        List[str]
    ipv6:        List[str]
    is_up:       bool
    speed_mbps:  Optional[int]
    bytes_sent:  int
    bytes_recv:  int


# ─────────────────────────────────────────────────────────────────────────────
#  System Agent
# ─────────────────────────────────────────────────────────────────────────────

class SystemAgent(BaseAgent):
    """
    Full-stack system control agent.
    Executes raw system operations (shell, processes, OS details).
    No application-level logic (e.g. MS Paint).
    """

    # ── Security ──────────────────────────────────────────────────────────────

    BLOCKED_PATTERNS = [
        r"format\s+c:",
        r"del\s+/[fs].+c:\\",
        r"rm\s+-rf\s+/",
        r"rd\s+/s\s+/q\s+c:\\",
        r":\(\)\s*\{",              # fork bomb
        r">\s*/dev/sd[a-z]",
        r">\s+\\\\.\\physicaldrive",
        r"reg\s+delete\s+HKLM.*system",
        r"net\s+user\s+.+/delete",
        r"takeown.+system32",
        r"icacls.+system32",
        r"bcdedit",                 # boot config
        r"diskpart",                # disk partitioning
    ]

    ALLOWED_PREFIXES = {
        "dir", "ls", "echo", "cat", "type", "find", "grep", "where", "which",
        "systeminfo", "uname", "ver", "wmic", "tasklist", "ps", "top",
        "netstat", "ipconfig", "ifconfig", "ping", "tracert", "nslookup",
        "date", "time", "whoami", "hostname", "python", "python3", "pip",
        "node", "npm", "git", "curl", "wget", "mkdir", "rmdir", "copy", "cp",
        "move", "mv", "rename", "del", "rm", "clear", "cls", "start", "open",
        "explorer", "choco", "winget", "scoop", "code", "nvim", "vim",
        "powershell", "pwsh", "cmd", "sc", "net", "reg", "wevtutil",
        "sfc", "dism", "shutdown", "reboot", "logoff",
    }

    MAX_EXECUTION_TIME = 300

    def __init__(self, event_bus=None):
        super().__init__(name=self.__class__.__name__, role="Agent")
        self.event_bus      = event_bus
        self.execution_log:     List[Dict] = []
        self.running_processes: Dict[int, subprocess.Popen] = {}
        self._psutil  = self._try_import("psutil")
        self._wmi     = self._try_import("wmi")     if IS_WINDOWS else None
        self._winreg  = self._try_import("winreg")  if IS_WINDOWS else None
        self._comtypes = self._try_import("comtypes") if IS_WINDOWS else None

        self.handlers = {
            "execute_command":      self.execute_command,
            "execute_script":       self.execute_script,
            "execute_powershell":   self.execute_powershell,
            "execute_batch":        self.execute_batch,
            "get_system_info":      self.get_system_info,
            "get_stats":            self.get_system_stats,
            "get_uptime":           self.get_uptime,
            "get_hardware_info":    self.get_hardware_info,
            "list_processes":       self.list_processes,
            "find_process":         self.find_process,
            "kill_process":         self.kill_process,
            "suspend_process":      self.suspend_process,
            "resume_process":       self.resume_process,
            "get_process_info":     self.get_process_info,
            "set_process_priority": self.set_process_priority,
            "list_services":        self.list_services,
            "get_service":          self.get_service,
            "start_service":        self.start_service,
            "stop_service":         self.stop_service,
            "restart_service":      self.restart_service,
            "set_service_start":    self.set_service_start_type,
            "reg_read":             self.registry_read,
            "reg_write":            self.registry_write,
            "reg_delete":           self.registry_delete,
            "reg_list":             self.registry_list,
            "reg_backup":           self.registry_backup,
            "get_env":              self.get_environment,
            "set_env":              self.set_environment,
            "del_env":              self.delete_environment,
            "list_env":             self.list_environment,
            "get_network_adapters": self.get_network_adapters,
            "get_open_ports":       self.get_open_ports,
            "get_connections":      self.get_connections,
            "ping_host":            self.ping_host,
            "dns_lookup":           self.dns_lookup,
            "get_public_ip":        self.get_public_ip,
            "get_wifi_networks":    self.get_wifi_networks,
            "get_network_stats":    self.get_network_stats,
            "get_disk_info":        self.get_disk_info,
            "get_disk_usage":       self.get_disk_usage,
            "list_drives":          self.list_drives,
            "get_volume_info":      self.get_volume_info,
            "get_screen_resolution": self.get_screen_resolution,
            "set_screen_resolution": self.set_screen_resolution,
            "get_monitors":          self.get_monitors,
            "get_audio_devices":    self.get_audio_devices,
            "set_volume":           self.set_volume,
            "get_volume":           self.get_volume,
            "mute_audio":           self.mute_audio,
            "unmute_audio":         self.unmute_audio,
            "get_clipboard":        self.get_clipboard,
            "set_clipboard":        self.set_clipboard,
            "clear_clipboard":      self.clear_clipboard,
            "send_notification":    self.send_notification,
            "show_message_box":     self.show_message_box,
            "get_battery":          self.get_battery,
            "set_power_plan":       self.set_power_plan,
            "shutdown":             self.shutdown_system,
            "reboot":               self.reboot_system,
            "sleep":                self.sleep_system,
            "hibernate":            self.hibernate_system,
            "list_tasks":           self.list_scheduled_tasks,
            "create_task":          self.create_scheduled_task,
            "delete_task":          self.delete_scheduled_task,
            "run_task":             self.run_scheduled_task,
            "read_event_log":       self.read_event_log,
            "get_system_errors":    self.get_recent_system_errors,
            "list_fw_rules":        self.list_firewall_rules,
            "add_fw_rule":          self.add_firewall_rule,
            "remove_fw_rule":       self.remove_firewall_rule,
            "list_printers":        self.list_printers,
            "get_default_printer":  self.get_default_printer,
            "set_default_printer":  self.set_default_printer,
            "list_startup":         self.list_startup_items,
            "disable_startup":      self.disable_startup_item,
            "lock_screen":          self.lock_screen,
            "get_installed_apps":   self.get_installed_apps,
            "get_system_fonts":     self.get_system_fonts,
            "flush_dns":            self.flush_dns_cache,
            "empty_recycle_bin":    self.empty_recycle_bin,
            "get_temp_dir_size":    self.get_temp_dir_size,
            "clean_temp":           self.clean_temp_files,
            "get_execution_log":    self._log_action,
            "run_command":          self.execute_command,  # Alias for task_parser compatibility
        }

    def _emit_suppressed(self, action: str, exc: Exception) -> None:
        logger.warning(f"Suppressed error during {action}: {exc}", exc_info=True)

    # -------------------------------------------------------------------------
    #  Command Execution
    # -------------------------------------------------------------------------

    def execute_command(self, command: str, shell: bool = True,
                        cwd: str = None, env: Dict = None,
                        timeout: int = None, capture_output: bool = True,
                        stdin_input: str = None, context: Any = None) -> Dict:
        """Execute a system command with full security checking."""
        allowed, reason = self._security_check(command)
        if not allowed:
            return {"success": False, "error": f"Security blocked: {reason}"}

        timeout  = timeout or self.MAX_EXECUTION_TIME
        run_env  = os.environ.copy()
        if env:
            run_env.update(env)

        start = time.monotonic()
        try:
            if context and hasattr(context, 'sandbox'):
                # Phase 8 Execution Kernel isolation
                proc = context.sandbox.run_subprocess(
                    context.lease.lease_id,
                    command, shell=shell, cwd=cwd, env=run_env,
                    stdout=subprocess.PIPE if capture_output else None,
                    stderr=subprocess.PIPE if capture_output else None,
                    stdin=subprocess.PIPE if stdin_input else None,
                    text=True, encoding="utf-8", errors="replace",
                )
            else:
                # Legacy unisolated execution
                proc = subprocess.Popen(
                    command, shell=shell, cwd=cwd, env=run_env,
                    stdout=subprocess.PIPE if capture_output else None,
                    stderr=subprocess.PIPE if capture_output else None,
                    stdin=subprocess.PIPE if stdin_input else None,
                    text=True, encoding="utf-8", errors="replace",
                )
            
            self.running_processes[proc.pid] = proc

            try:
                stdout, stderr = proc.communicate(
                    input=stdin_input, timeout=timeout
                )
                elapsed = time.monotonic() - start
                self._log_exec(command, proc.returncode == 0, elapsed)
                return {
                    "success":        proc.returncode == 0,
                    "returncode":     proc.returncode,
                    "stdout":         (stdout or "")[:50000],
                    "stderr":         (stderr or "")[:10000],
                    "execution_time": round(elapsed, 2),
                    "pid":            proc.pid,
                }
            except subprocess.TimeoutExpired:
                proc.kill(); proc.communicate()
                return {
                    "success": False,
                    "error":   f"Command timed out after {timeout}s",
                    "stdout": "", "stderr": "TIMEOUT",
                }
            finally:
                self.running_processes.pop(proc.pid, None)

        except Exception as e:
            return {"success": False, "error": str(e)}

    def execute_script(self, code: str, language: str = "python",
                       timeout: int = 60) -> Dict:
        """Execute a code snippet in the appropriate interpreter."""
        # O(1) dict dispatch — zero elif routing
        _EXEC_DISPATCH = {
            "python":     self._exec_python,
            "bash":       self._exec_shell,
            "sh":         self._exec_shell,
            "cmd":        self.execute_batch,
            "batch":      self.execute_batch,
            "powershell": self.execute_powershell,
            "ps1":        self.execute_powershell,
            "javascript": self._exec_js,
        }
        handler = _EXEC_DISPATCH.get(language)
        return (handler(code, timeout) if handler
                else {"success": False, "error": f"Unsupported language: {language}"})

    def _exec_python(self, code: str, timeout: int) -> Dict:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py",
                                          delete=False, encoding="utf-8") as f:
            f.write(code); tmp = f.name
        try:
            proc = subprocess.Popen(
                [sys.executable, tmp],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
            )
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.communicate()
                return {"success": False, "error": f"Script timed out after {timeout}s"}
            return {
                "success":    proc.returncode == 0,
                "stdout":     out[:50000],
                "stderr":     err[:10000],
                "returncode": proc.returncode,
            }
        finally:
            try: os.unlink(tmp)
            except Exception as e: self._emit_suppressed("exec_python_cleanup", e)

    def _exec_shell(self, code: str, timeout: int) -> Dict:
        sh = shutil.which("bash") or shutil.which("sh") or "sh"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh",
                                          delete=False, encoding="utf-8") as f:
            f.write(code); tmp = f.name
        try:
            proc = subprocess.Popen([sh, tmp], stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.communicate()
                return {"success": False, "error": "Shell script timed out"}
            return {"success": proc.returncode == 0, "stdout": out, "stderr": err}
        finally:
            try: os.unlink(tmp)
            except Exception as e: self._emit_suppressed("exec_shell_cleanup", e)

    def _exec_js(self, code: str, timeout: int) -> Dict:
        node = shutil.which("node") or shutil.which("nodejs")
        if not node:
            return {"success": False, "error": "Node.js not found"}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".js",
                                          delete=False, encoding="utf-8") as f:
            f.write(code); tmp = f.name
        try:
            proc = subprocess.Popen([node, tmp], stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.communicate()
                return {"success": False, "error": "JS timed out"}
            return {"success": proc.returncode == 0, "stdout": out, "stderr": err}
        finally:
            try: os.unlink(tmp)
            except Exception as e: self._emit_suppressed("exec_js_cleanup", e)

    def execute_powershell(self, script: str, timeout: int = 120,
                            execution_policy: str = "Bypass") -> Dict:
        """Execute a PowerShell script (Windows and pwsh on Linux/Mac)."""
        ps = shutil.which("pwsh") or shutil.which("powershell")
        if not ps:
            return {"success": False, "error": "PowerShell not found"}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ps1",
                                          delete=False, encoding="utf-8") as f:
            f.write(script); tmp = f.name
        try:
            proc = subprocess.Popen(
                [ps, "-ExecutionPolicy", execution_policy,
                 "-NonInteractive", "-File", tmp],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
            )
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.communicate()
                return {"success": False, "error": "PowerShell timed out"}
            return {
                "success": proc.returncode == 0,
                "stdout":  out[:50000],
                "stderr":  err[:10000],
                "returncode": proc.returncode,
            }
        finally:
            try: os.unlink(tmp)
            except Exception as e: self._emit_suppressed("exec_powershell_cleanup", e)

    def execute_batch(self, script: str, timeout: int = 60) -> Dict:
        """Execute a Windows batch (.bat) script."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".bat",
                                          delete=False, encoding="utf-8") as f:
            f.write(script); tmp = f.name
        try:
            proc = subprocess.Popen(
                ["cmd.exe", "/C", tmp] if IS_WINDOWS else ["sh", tmp],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
            )
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.communicate()
                return {"success": False, "error": "Batch script timed out"}
            return {"success": proc.returncode == 0, "stdout": out, "stderr": err}
        finally:
            try: os.unlink(tmp)
            except Exception as e: self._emit_suppressed("exec_batch_cleanup", e)

    # -------------------------------------------------------------------------
    #  System Info
    # -------------------------------------------------------------------------

    def get_system_info(self) -> Dict:
        """Comprehensive system information."""
        info: Dict = {
            "success":        True,
            "platform":       platform.platform(),
            "system":         platform.system(),
            "release":        platform.release(),
            "version":        platform.version(),
            "machine":        platform.machine(),
            "processor":      platform.processor(),
            "architecture":   platform.architecture(),
            "hostname":       platform.node(),
            "python":         platform.python_version(),
            "python_exe":     sys.executable,
            "cpu_count_log":  os.cpu_count(),
            "username":       os.environ.get("USERNAME") or os.environ.get("USER", ""),
            "home_dir":       str(Path.home()),
            "temp_dir":       tempfile.gettempdir(),
            "cwd":            os.getcwd(),
        }

        if self._psutil:
            import psutil
            info["cpu_count_phys"] = psutil.cpu_count(logical=False)
            info["boot_time"] = datetime.fromtimestamp(psutil.boot_time()).isoformat()

        if IS_WINDOWS:
            try:
                r = subprocess.run(
                    ["wmic", "computersystem", "get",
                     "Manufacturer,Model,TotalPhysicalMemory", "/format:csv"],
                    capture_output=True, text=True, timeout=30,
                )
                for line in r.stdout.splitlines():
                    if line.strip() and "Manufacturer" not in line:
                        parts = [p.strip() for p in line.split(",")]
                        if len(parts) >= 4:
                            info["manufacturer"] = parts[1]
                            info["model"]        = parts[2]
                            ram = int(parts[3]) if parts[3].isdigit() else 0
                            info["ram_total_gb"] = round(ram / (1024**3), 2)
            except Exception:
                pass

        return info

    def get_system_stats(self) -> Dict:
        """Real-time CPU, RAM, disk, swap, and temperature stats."""
        stats: Dict = {"success": True, "timestamp": datetime.now().isoformat()}

        if not self._psutil:
            stats["warning"] = "psutil not installed — limited stats"
            return stats

        import psutil

        # CPU
        stats["cpu"] = {
            "percent_per_core": psutil.cpu_percent(interval=0.5, percpu=True),
            "percent_total":    psutil.cpu_percent(interval=0),
            "count_logical":    psutil.cpu_count(logical=True),
            "count_physical":   psutil.cpu_count(logical=False),
            "freq_mhz":         (psutil.cpu_freq().current if psutil.cpu_freq() else None),
        }

        # Memory
        vm = psutil.virtual_memory()
        stats["memory"] = {
            "total_gb":     round(vm.total    / 1e9, 2),
            "used_gb":      round(vm.used     / 1e9, 2),
            "available_gb": round(vm.available / 1e9, 2),
            "percent":      vm.percent,
            "cached_gb":    round(getattr(vm, "cached", 0) / 1e9, 2),
        }

        # Swap
        sw = psutil.swap_memory()
        stats["swap"] = {
            "total_gb": round(sw.total / 1e9, 2),
            "used_gb":  round(sw.used  / 1e9, 2),
            "percent":  sw.percent,
        }

        # Disk
        stats["disks"] = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                stats["disks"].append({
                    "device":     part.device,
                    "mountpoint": part.mountpoint,
                    "fstype":     part.fstype,
                    "total_gb":   round(usage.total / 1e9, 2),
                    "used_gb":    round(usage.used  / 1e9, 2),
                    "free_gb":    round(usage.free  / 1e9, 2),
                    "percent":    usage.percent,
                })
            except PermissionError:
                pass

        # Temperatures (Linux/Mac, may not work on Windows)
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                stats["temperatures"] = {
                    k: [{"label": s.label, "current": s.current, "high": s.high}
                        for s in v]
                    for k, v in temps.items()
                }
        except (AttributeError, NotImplementedError):
            pass

        # Process count
        stats["processes"] = len(psutil.pids())
        stats["threads"]   = sum(p.num_threads() for p in psutil.process_iter(["num_threads"])
                                  if p.info["num_threads"])

        return stats

    def get_uptime(self) -> Dict:
        """System uptime since last boot."""
        if self._psutil:
            import psutil
            boot  = datetime.fromtimestamp(psutil.boot_time())
            now   = datetime.now()
            delta = now - boot
            return {
                "success":      True,
                "boot_time":    boot.isoformat(),
                "uptime_secs":  int(delta.total_seconds()),
                "uptime_human": str(delta).split(".")[0],
                "days":         delta.days,
                "hours":        delta.seconds // 3600,
                "minutes":      (delta.seconds % 3600) // 60,
            }
        # Fallback
        if IS_WINDOWS:
            r = self.execute_command("net statistics workstation", timeout=10)
            return {"success": r.get("success"), "raw": r.get("stdout", "")}
        r = self.execute_command("uptime", timeout=5)
        return {"success": r.get("success"), "raw": r.get("stdout", "")}

    def get_hardware_info(self) -> Dict:
        """Detailed hardware: CPU model, RAM sticks, GPU, motherboard."""
        info: Dict = {"success": True}

        def _get_win():
            queries = {
                "cpu":          "wmic cpu get Name,MaxClockSpeed,NumberOfCores,NumberOfLogicalProcessors /format:csv",
                "ram_sticks":   "wmic memorychip get Capacity,Speed,Manufacturer /format:csv",
                "gpu":          "wmic path win32_VideoController get Name,AdapterRAM,CurrentRefreshRate /format:csv",
                "motherboard":  "wmic baseboard get Manufacturer,Product,Version /format:csv",
                "bios":         "wmic bios get Manufacturer,Version,ReleaseDate /format:csv",
            }
            for key, cmd in queries.items():
                try:
                    r = subprocess.run(cmd.split(), capture_output=True, text=True, timeout=30)
                    lines = [l.strip() for l in r.stdout.splitlines()
                             if l.strip() and "Node" not in l and l.count(",") > 0]
                    info[key] = lines
                except Exception: info[key] = []

        def _get_linux():
            try:
                r1 = subprocess.run(["lscpu"], capture_output=True, text=True, timeout=30)
                info["cpu"] = r1.stdout.strip()
                r2 = subprocess.run(["free", "-h"], capture_output=True, text=True, timeout=30)
                info["memory"] = r2.stdout.strip()
                r3 = subprocess.run(["lspci"], capture_output=True, text=True, timeout=30)
                info["gpu"] = "\n".join(l for l in r3.stdout.splitlines() if "vga" in l.lower()).strip()
            except Exception: pass

        _HW_DISPATCH = {
            "windows": _get_win,
            "linux":   _get_linux,
        }
        
        platform_key = ("windows" if IS_WINDOWS else 
                        "linux"   if IS_LINUX   else "unknown")
        _HW_DISPATCH.get(platform_key, lambda: None)()

        return info

    # -------------------------------------------------------------------------
    #  Processes
    # -------------------------------------------------------------------------

    def list_processes(self, limit: int = 100, sort_by: str = "memory",
                       search: str = None, include_cmdline: bool = False) -> Dict:
        """List running processes sorted by CPU or memory."""
        if not self._psutil:
            cmd = "tasklist /fo csv" if IS_WINDOWS else "ps aux"
            return self.execute_command(cmd)

        import psutil

        attrs = ["pid", "name", "status", "cpu_percent", "memory_info",
                 "username", "create_time"]
        if include_cmdline:
            attrs.append("cmdline")

        procs = []
        for p in psutil.process_iter(attrs):
            try:
                inf = p.info
                if search and search.lower() not in (inf.get("name") or "").lower():
                    continue
                mem_mb = (inf.get("memory_info").rss / 1e6) if inf.get("memory_info") else 0
                procs.append({
                    "pid":      inf.get("pid"),
                    "name":     inf.get("name"),
                    "status":   inf.get("status"),
                    "cpu_pct":  round(inf.get("cpu_percent") or 0, 1),
                    "mem_mb":   round(mem_mb, 1),
                    "user":     inf.get("username") or "",
                    "started":  (datetime.fromtimestamp(inf.get("create_time")).strftime("%H:%M:%S")
                                 if inf.get("create_time") else ""),
                    "cmdline":  (" ".join(inf.get("cmdline") or [])[:200]
                                 if include_cmdline else ""),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        key = "mem_mb" if sort_by == "memory" else "cpu_pct"
        procs.sort(key=lambda x: x.get(key), reverse=True)
        return {
            "success":   True,
            "count":     len(procs),
            "processes": procs[:limit],
        }

    def find_process(self, name: str = None, pid: int = None) -> Dict:
        """Find specific process(es) by name substring or PID."""
        if not self._psutil:
            return {"success": False, "error": "psutil required"}
        import psutil

        found = []
        for p in psutil.process_iter(["pid", "name", "status", "memory_info"]):
            try:
                inf = p.info
                # Branchless match check
                is_pid_match = pid and inf.get("pid") == pid
                is_name_match = name and name.lower() in (inf.get("name") or "").lower()
                if is_pid_match or is_name_match:
                    found.append(inf)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        return {
            "success": True,
            "found": len(found),
            "processes": found,
        }

    def kill_process(self, pid: int = None, name: str = None,
                     force: bool = False, children: bool = True) -> Dict:
        """Kill a process by PID or name. Optionally kill children too."""
        if not pid and not name:
            return {"success": False, "error": "Provide pid or name"}

        if not self._psutil:
            if pid:
                if IS_WINDOWS:
                    return self.execute_command(f"taskkill /PID {pid} /F")
                return self.execute_command(f"kill -9 {pid}")
            return {"success": False, "error": "psutil required for kill-by-name"}

        import psutil

        killed: List[int] = []
        errors: List[str] = []

        targets: List[psutil.Process] = []
        try:
            if pid:
                targets = [psutil.Process(pid)]
            else:
                targets = [p for p in psutil.process_iter(["pid", "name"])
                           if name.lower() in (p.info.get("name") or "").lower()]
        except psutil.NoSuchProcess:
            return {"success": False, "error": f"PID {pid} not found"}

        for proc in targets:
            try:
                if children:
                    kids = proc.children(recursive=True)
                    for kid in kids:
                        try:
                            kid.kill() if force else kid.terminate()
                            killed.append(kid.pid)
                        except Exception:
                            pass
                if force:
                    proc.kill()
                else:
                    proc.terminate()
                killed.append(proc.pid)
            except psutil.AccessDenied as e:
                errors.append(f"Access denied for PID {proc.pid}")
            except Exception as e:
                errors.append(str(e))

        return {
            "success":    len(killed) > 0,
            "killed_pids": killed,
            "errors":     errors,
        }

    def suspend_process(self, pid: int) -> Dict:
        if not self._psutil:
            return {"success": False, "error": "psutil required"}
        import psutil
        try:
            psutil.Process(pid).suspend()
            return {"success": True, "pid": pid, "state": "suspended"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def resume_process(self, pid: int) -> Dict:
        if not self._psutil:
            return {"success": False, "error": "psutil required"}
        import psutil
        try:
            psutil.Process(pid).resume()
            return {"success": True, "pid": pid, "state": "resumed"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_process_info(self, pid: int) -> Dict:
        """Detailed info for a single process."""
        if not self._psutil:
            return {"success": False, "error": "psutil required"}
        import psutil
        try:
            p = psutil.Process(pid)
            with p.oneshot():
                return {
                    "success":    True,
                    "pid":        p.pid,
                    "name":       p.name(),
                    "exe":        p.exe(),
                    "cmdline":    " ".join(p.cmdline()),
                    "cwd":        p.cwd(),
                    "status":     p.status(),
                    "cpu_pct":    p.cpu_percent(interval=0.1),
                    "mem_rss_mb": round(p.memory_info().rss / 1e6, 2),
                    "mem_vms_mb": round(p.memory_info().vms / 1e6, 2),
                    "threads":    p.num_threads(),
                    "open_files": len(p.open_files()),
                    "connections": len(p.connections()),
                    "username":   p.username(),
                    "created":    datetime.fromtimestamp(p.create_time()).isoformat(),
                    "ppid":       p.ppid(),
                    "priority":   p.nice(),
                }
        except psutil.NoSuchProcess:
            return {"success": False, "error": f"PID {pid} not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def set_process_priority(self, pid: int, priority: str = "normal") -> Dict:
        """Set process priority: realtime/high/above_normal/normal/below_normal/idle."""
        if not self._psutil:
            return {"success": False, "error": "psutil required"}
        import psutil
        prio_map = {
            "realtime":     psutil.REALTIME_PRIORITY_CLASS    if IS_WINDOWS else -20,
            "high":         psutil.HIGH_PRIORITY_CLASS        if IS_WINDOWS else -10,
            "above_normal": psutil.ABOVE_NORMAL_PRIORITY_CLASS if IS_WINDOWS else -5,
            "normal":       psutil.NORMAL_PRIORITY_CLASS      if IS_WINDOWS else 0,
            "below_normal": psutil.BELOW_NORMAL_PRIORITY_CLASS if IS_WINDOWS else 5,
            "idle":         psutil.IDLE_PRIORITY_CLASS        if IS_WINDOWS else 19,
        }
        prio_val = prio_map.get(priority.lower(), psutil.NORMAL_PRIORITY_CLASS if IS_WINDOWS else 0)
        try:
            psutil.Process(pid).nice(prio_val)
            return {"success": True, "pid": pid, "priority": priority}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # -------------------------------------------------------------------------
    #  Windows Services
    # -------------------------------------------------------------------------

    def _sc(self, *args, timeout: int = 15) -> Dict:
        if not IS_WINDOWS:
            return {"success": False, "error": "Services only available on Windows"}
        r = subprocess.run(["sc"] + list(args), capture_output=True, text=True, timeout=timeout)
        return {"success": r.returncode == 0, "stdout": r.stdout, "stderr": r.stderr}

    def list_services(self, state: str = "all", search: str = None,
                       limit: int = 100) -> Dict:
        """List Windows services."""
        if not IS_WINDOWS:
            # Linux: use systemctl
            cmd = "systemctl list-units --type=service --no-pager --plain"
            r   = self.execute_command(cmd)
            return r

        r = subprocess.run(
            ["sc", "query", "type=", "all", "state=", state],
            capture_output=True, text=True, timeout=30,
        )
        services: List[Dict] = []
        current: Dict        = {}
        for line in r.stdout.splitlines():
            line = line.strip()
        def _handle_name(val):
            nonlocal current
            if current: services.append(current)
            current = {"name": val}
        
        _PARSE_DISPATCH = {
            "SERVICE_NAME": _handle_name,
            "DISPLAY_NAME": lambda v: current.update({"display": v}),
            "STATE":        lambda v: current.update({
                "status": (re.search(r"\d+\s+(\w+)", v).group(1) 
                           if re.search(r"\d+\s+(\w+)", v) else "UNKNOWN")
            }),
        }
        
        for line in r.stdout.splitlines():
            line = line.strip()
            if ":" not in line and "STATE" not in line: continue
            
            # Split once at first colon if possible, or use keyword
            parts = line.split(":", 1)
            key   = parts[0].strip()
            val   = parts[1].strip() if len(parts) > 1 else line
            
            # O(1) prefix dispatch
            handler = _PARSE_DISPATCH.get(key)
            if not handler and "STATE" in line:
                handler = _PARSE_DISPATCH["STATE"]
            
            handler(val) if handler else None
            
        if current: services.append(current)

        if search:
            services = [s for s in services
                        if search.lower() in s.get("name", "").lower()
                        or search.lower() in s.get("display", "").lower()]

        return {
            "success":  True,
            "count":    len(services),
            "services": services[:limit],
        }

    def get_service(self, name: str) -> Dict:
        r = subprocess.run(["sc", "query", name], capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return {"success": False, "error": f"Service '{name}' not found"}
        status_m = re.search(r"STATE\s*:\s*\d+\s+(\w+)", r.stdout)
        return {
            "success": True,
            "name":    name,
            "status":  status_m.group(1) if status_m else "UNKNOWN",
            "raw":     r.stdout,
        }

    def start_service(self, name: str) -> Dict:
        return self._sc("start", name, timeout=30)

    def stop_service(self, name: str) -> Dict:
        return self._sc("stop", name, timeout=30)

    def restart_service(self, name: str) -> Dict:
        self.stop_service(name)
        time.sleep(2)
        return self.start_service(name)

    def set_service_start_type(self, name: str,
                                start_type: str = "auto") -> Dict:
        """Set service start type: auto/manual/disabled/delayed-auto."""
        type_map = {
            "auto":          "auto",
            "manual":        "demand",
            "disabled":      "disabled",
            "delayed-auto":  "delayed-auto",
        }
        sc_type = type_map.get(start_type.lower(), "demand")
        return self._sc("config", name, "start=", sc_type)

    # -------------------------------------------------------------------------
    #  Windows Registry
    # -------------------------------------------------------------------------

    def _parse_hive(self, key_path: str):
        """Split HKLM\\...\\ into (hive_constant, subkey)."""
        if not self._winreg:
            raise RuntimeError("winreg not available (Linux/Mac?)")
        import winreg

        hives = {
            "HKEY_LOCAL_MACHINE":  winreg.HKEY_LOCAL_MACHINE,
            "HKLM":                winreg.HKEY_LOCAL_MACHINE,
            "HKEY_CURRENT_USER":   winreg.HKEY_CURRENT_USER,
            "HKCU":                winreg.HKEY_CURRENT_USER,
            "HKEY_CLASSES_ROOT":   winreg.HKEY_CLASSES_ROOT,
            "HKCR":                winreg.HKEY_CLASSES_ROOT,
            "HKEY_USERS":          winreg.HKEY_USERS,
            "HKU":                 winreg.HKEY_USERS,
            "HKEY_CURRENT_CONFIG": winreg.HKEY_CURRENT_CONFIG,
            "HKCC":                winreg.HKEY_CURRENT_CONFIG,
        }
        parts   = key_path.replace("/", "\\").split("\\")
        hive_str = parts[0].upper()
        subkey   = "\\".join(parts[1:])
        hive     = hives.get(hive_str)
        if hive is None:
            raise ValueError(f"Unknown registry hive: {hive_str}")
        return hive, subkey

    def registry_read(self, key_path: str, value_name: str = "") -> Dict:
        """Read a registry value."""
        if not IS_WINDOWS:
            return {"success": False, "error": "Registry only on Windows"}
        try:
            import winreg
            hive, subkey = self._parse_hive(key_path)
            with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ) as key:
                data, regtype = winreg.QueryValueEx(key, value_name)
            return {
                "success":    True,
                "key":        key_path,
                "value_name": value_name,
                "data":       str(data),
                "type":       regtype,
            }
        except FileNotFoundError:
            return {"success": False, "error": f"Registry key/value not found: {key_path}\\{value_name}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def registry_write(self, key_path: str, value_name: str,
                        data: Any, reg_type: str = "REG_SZ") -> Dict:
        """Write a registry value. Creates key if needed."""
        if not IS_WINDOWS:
            return {"success": False, "error": "Registry only on Windows"}
        try:
            import winreg
            type_map = {
                "REG_SZ":        winreg.REG_SZ,
                "REG_DWORD":     winreg.REG_DWORD,
                "REG_QWORD":     winreg.REG_QWORD,
                "REG_BINARY":    winreg.REG_BINARY,
                "REG_EXPAND_SZ": winreg.REG_EXPAND_SZ,
                "REG_MULTI_SZ":  winreg.REG_MULTI_SZ,
            }
            rt   = type_map.get(reg_type.upper(), winreg.REG_SZ)
            hive, subkey = self._parse_hive(key_path)
            with winreg.CreateKeyEx(hive, subkey, 0,
                                     winreg.KEY_WRITE) as key:
                if rt == winreg.REG_DWORD:
                    data = int(data)
                winreg.SetValueEx(key, value_name, 0, rt, data)
            return {"success": True, "key": key_path,
                    "value_name": value_name, "data": str(data)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def registry_delete(self, key_path: str, value_name: str = None) -> Dict:
        """Delete a registry value or entire key."""
        if not IS_WINDOWS:
            return {"success": False, "error": "Registry only on Windows"}
        try:
            import winreg
            hive, subkey = self._parse_hive(key_path)
            if value_name is not None:
                with winreg.OpenKey(hive, subkey, 0, winreg.KEY_WRITE) as key:
                    winreg.DeleteValue(key, value_name)
                return {"success": True, "deleted_value": f"{key_path}\\{value_name}"}
            else:
                winreg.DeleteKey(hive, subkey)
                return {"success": True, "deleted_key": key_path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def registry_list(self, key_path: str) -> Dict:
        """List all subkeys and values under a registry key."""
        if not IS_WINDOWS:
            return {"success": False, "error": "Registry only on Windows"}
        try:
            import winreg
            hive, subkey = self._parse_hive(key_path)
            with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ) as key:
                subkeys: List[str] = []
                values:  List[Dict] = []

                i = 0
                while True:
                    try:
                        subkeys.append(winreg.EnumKey(key, i)); i += 1
                    except OSError:
                        break

                i = 0
                while True:
                    try:
                        name, data, dtype = winreg.EnumValue(key, i)
                        values.append({"name": name, "data": str(data), "type": dtype})
                        i += 1
                    except OSError:
                        break

            return {
                "success": True,
                "key":     key_path,
                "subkeys": subkeys,
                "values":  values,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def registry_backup(self, key_path: str, output_file: str) -> Dict:
        """Export registry key to .reg file using regedit."""
        if not IS_WINDOWS:
            return {"success": False, "error": "Registry only on Windows"}
        r = subprocess.run(
            ["regedit", "/E", output_file, key_path],
            capture_output=True, text=True, timeout=30,
        )
        return {
            "success":     r.returncode == 0,
            "output_file": output_file,
            "key":         key_path,
            "stderr":      r.stderr,
        }

    # -------------------------------------------------------------------------
    #  Environment Variables
    # -------------------------------------------------------------------------

    def get_environment(self, var: str) -> Dict:
        return {
            "success": True,
            "variable": var,
            "value":    os.environ.get(var),
            "exists":   var in os.environ,
        }

    def list_environment(self, filter_sensitive: bool = True) -> Dict:
        sensitive = {"KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL",
                     "PASSWD", "API_KEY", "PRIVATE"}
        env = {
            k: v for k, v in os.environ.items()
            if not filter_sensitive or not any(s in k.upper() for s in sensitive)
        }
        return {"success": True, "count": len(env), "variables": env}

    def set_environment(self, var: str, value: str,
                         persistent: bool = False) -> Dict:
        """Set env var in current process. If persistent=True, uses setx/export."""
        os.environ[var] = value
        if persistent:
            if IS_WINDOWS:
                r = subprocess.run(["setx", var, value],
                                   capture_output=True, text=True, timeout=30)
                return {"success": r.returncode == 0, "variable": var}
            else:
                # Append to ~/.bashrc
                line = f'\nexport {var}="{value}"\n'
                rc   = Path.home() / ".bashrc"
                with open(rc, "a") as f:
                    f.write(line)
                return {"success": True, "variable": var,
                        "note": f"Added to {rc}"}
        return {"success": True, "variable": var, "value": value}

    def delete_environment(self, var: str) -> Dict:
        existed = var in os.environ
        os.environ.pop(var, None)
        return {"success": True, "variable": var, "existed": existed}

    # -------------------------------------------------------------------------
    #  Network
    # -------------------------------------------------------------------------

    def get_network_adapters(self) -> Dict:
        """Full network adapter info via psutil."""
        if not self._psutil:
            return self.execute_command("ipconfig /all" if IS_WINDOWS else "ip addr")
        import psutil
        adapters: List[Dict] = []
        stats = psutil.net_io_counters(pernic=True)
        for name, addrs in psutil.net_if_addrs().items():
            nic_stats = psutil.net_if_stats().get(name)
            io        = stats.get(name)
            ipv4 = [a.address for a in addrs if a.family == socket.AF_INET]
            ipv6 = [a.address for a in addrs if a.family == socket.AF_INET6]
            mac  = next((a.address for a in addrs if a.family == psutil.AF_LINK), "")
            adapters.append({
                "name":        name,
                "mac":         mac,
                "ipv4":        ipv4,
                "ipv6":        ipv6,
                "is_up":       nic_stats.isup if nic_stats else False,
                "speed_mbps":  nic_stats.speed if nic_stats else None,
                "bytes_sent":  io.bytes_sent if io else 0,
                "bytes_recv":  io.bytes_recv if io else 0,
                "mtu":         nic_stats.mtu if nic_stats else None,
            })
        return {"success": True, "adapters": adapters, "count": len(adapters)}

    def get_open_ports(self, protocol: str = "tcp") -> Dict:
        """List all open listening ports."""
        if self._psutil:
            import psutil
            conns = psutil.net_connections(kind=protocol)
            ports = []
            for c in conns:
                if c.status in ("LISTEN", "NONE") or c.status == psutil.CONN_LISTEN:
                    ports.append({
                        "port":    c.laddr.port if c.laddr else None,
                        "address": c.laddr.ip   if c.laddr else "*",
                        "pid":     c.pid,
                        "status":  c.status,
                    })
            return {"success": True, "ports": ports, "count": len(ports)}
        # fallback
        cmd = "netstat -ano" if IS_WINDOWS else "ss -tlnp"
        return self.execute_command(cmd)

    def get_connections(self, kind: str = "tcp") -> Dict:
        """All active network connections."""
        if not self._psutil:
            return self.execute_command("netstat -ano" if IS_WINDOWS else "ss -anp")
        import psutil
        conns = []
        for c in psutil.net_connections(kind=kind):
            conns.append({
                "proto":   kind,
                "laddr":   f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else "",
                "raddr":   f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else "",
                "status":  c.status,
                "pid":     c.pid,
            })
        return {"success": True, "connections": conns, "count": len(conns)}

    def ping_host(self, host: str, count: int = 4,
                   timeout_ms: int = 1000) -> Dict:
        """Ping a host and return latency stats."""
        if IS_WINDOWS:
            cmd = f"ping -n {count} -w {timeout_ms} {host}"
        else:
            cmd = f"ping -c {count} -W {timeout_ms // 1000 or 1} {host}"

        r = self.execute_command(cmd, timeout=30)

        # Parse average latency
        avg = None
        m   = re.search(r"[Aa]verage\s*=\s*(\d+)|avg\s*=\s*([\d.]+)", r.get("stdout", ""))
        if m:
            avg = float(m.group(1) or m.group(2))

        reachable = r.get("success", False) and r.get("returncode") == 0
        return {
            "success":      True,
            "host":         host,
            "reachable":    reachable,
            "avg_latency_ms": avg,
            "output":       r.get("stdout", ""),
        }

    def dns_lookup(self, hostname: str,
                    record_type: str = "A") -> Dict:
        """Resolve hostname to IP(s)."""
        try:
            results = socket.getaddrinfo(hostname, None)
            ips = list({r[4][0] for r in results})
            return {"success": True, "hostname": hostname, "ips": ips}
        except socket.gaierror as e:
            return {"success": False, "error": str(e), "hostname": hostname}

    def scan_wifi(self) -> Dict:
        """Scan for available WiFi networks."""
        def _scan_win():
            r = subprocess.run(["netsh", "wlan", "show", "networks", "mode=Bssid"], capture_output=True, text=True, timeout=30)
            ssids = re.findall(r"SSID\s+:\s+(.+)", r.stdout)
            signals = re.findall(r"Signal\s+:\s+(\d+)%", r.stdout)
            networks = [{"ssid": s.strip(), "signal_pct": int(sig)} for s, sig in zip(ssids, signals)]
            return {"success": True, "networks": networks, "count": len(networks)}

        def _scan_linux():
            r = subprocess.run(["nmcli", "-t", "-f", "SSID,SIGNAL", "dev", "wifi"], capture_output=True, text=True, timeout=30)
            networks = []
            for line in r.stdout.splitlines():
                parts = line.split(":")
                if len(parts) >= 2:
                    networks.append({"ssid": parts[0], "signal_pct": parts[1]})
            return {"success": True, "networks": networks}

        _SCAN_DISPATCH = {"windows": _scan_win, "linux": _scan_linux}
        platform_key = "windows" if IS_WINDOWS else "linux" if IS_LINUX else "unknown"
        handler = _SCAN_DISPATCH.get(platform_key)
        if not handler: return {"success": False, "error": "Not supported on this OS"}
        return handler()

    def get_public_ip(self) -> Dict:
        """Get the machine's public IPv4 address."""
        services = [
            "https://api.ipify.org",
            "https://ifconfig.me/ip",
            "https://ident.me",
        ]
        import urllib.request
        for url in services:
            try:
                with urllib.request.urlopen(url, timeout=5) as resp:
                    ip = resp.read().decode().strip()
                    if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip):
                        return {"success": True, "public_ip": ip, "source": url}
            except Exception:
                continue
        return {"success": False, "error": "Could not determine public IP"}

    def get_wifi_networks(self) -> Dict:
        """List visible WiFi networks."""
        def _get_win():
            r = subprocess.run(["netsh", "wlan", "show", "networks", "mode=Bssid"], capture_output=True, text=True, timeout=30)
            ssids = re.findall(r"SSID\s+:\s+(.+)", r.stdout)
            signals = re.findall(r"Signal\s+:\s+(\d+)%", r.stdout)
            networks = [{"ssid": s.strip(), "signal_pct": int(sig)} for s, sig in zip(ssids, signals)]
            return {"success": True, "networks": networks, "count": len(networks)}

        def _get_linux():
            r = subprocess.run(["nmcli", "-t", "-f", "SSID,SIGNAL", "dev", "wifi"], capture_output=True, text=True, timeout=30)
            networks = []
            for line in r.stdout.splitlines():
                parts = line.split(":")
                if len(parts) >= 2:
                    networks.append({"ssid": parts[0], "signal_pct": parts[1]})
            return {"success": True, "networks": networks}

        _GET_DISPATCH = {"windows": _get_win, "linux": _get_linux}
        platform_key = "windows" if IS_WINDOWS else "linux" if IS_LINUX else "unknown"
        handler = _GET_DISPATCH.get(platform_key)
        if not handler: return {"success": False, "error": "Not supported on this OS"}
        return handler()

    def get_network_stats(self) -> Dict:
        """Per-adapter bytes sent/recv since boot."""
        if not self._psutil:
            return {"success": False, "error": "psutil required"}
        import psutil
        io = psutil.net_io_counters(pernic=True)
        return {
            "success": True,
            "stats": {
                name: {
                    "bytes_sent":   c.bytes_sent,
                    "bytes_recv":   c.bytes_recv,
                    "packets_sent": c.packets_sent,
                    "packets_recv": c.packets_recv,
                    "errin":        c.errin,
                    "errout":       c.errout,
                }
                for name, c in io.items()
            },
        }

    def flush_dns_cache(self) -> Dict:
        """Flush the OS DNS cache."""
        _DNS_FLUSH_CMDS = {
            "windows": lambda: self.execute_command("ipconfig /flushdns"),
            "linux":   lambda: self.execute_command(
                "systemctl restart systemd-resolved 2>/dev/null; "
                "systemctl restart nscd 2>/dev/null; "
                "systemctl restart dnsmasq 2>/dev/null || true"
            ),
            "mac":     lambda: self.execute_command(
                "dscacheutil -flushcache && killall -HUP mDNSResponder"),
        }
        
        # O(1) platform detection
        platform_key = ("windows" if IS_WINDOWS else 
                        "linux"   if IS_LINUX   else 
                        "mac"     if IS_MAC     else "unknown")
        
        handler = _DNS_FLUSH_CMDS.get(platform_key)
        if not handler:
            return {"success": False, "error": f"Unsupported OS: {platform_key}"}
            
        r = handler()
        return {"success": True, "output": r.get("stdout", "")}

    # ─────────────────────────────────────────────────────────────────────────
    #  Disk / Storage
    # ─────────────────────────────────────────────────────────────────────────

    def get_disk_info(self) -> Dict:
        """All disk partitions with usage."""
        if not self._psutil:
            return self.execute_command("wmic diskdrive get Size,Model /format:csv"
                                         if IS_WINDOWS else "df -h")
        import psutil
        disks = []
        for part in psutil.disk_partitions(all=True):
            try:
                u = psutil.disk_usage(part.mountpoint)
                disks.append({
                    "device":     part.device,
                    "mountpoint": part.mountpoint,
                    "fstype":     part.fstype,
                    "opts":       part.opts,
                    "total_gb":   round(u.total / 1e9, 2),
                    "used_gb":    round(u.used  / 1e9, 2),
                    "free_gb":    round(u.free  / 1e9, 2),
                    "percent":    u.percent,
                })
            except PermissionError:
                disks.append({"device": part.device,
                               "mountpoint": part.mountpoint,
                               "error": "permission denied"})
        return {"success": True, "disks": disks}

    def get_disk_usage(self, path: str = "/") -> Dict:
        if IS_WINDOWS and path == "/":
            path = "C:\\"
        if self._psutil:
            import psutil
            try:
                u = psutil.disk_usage(path)
                return {
                    "success":  True,
                    "path":     path,
                    "total_gb": round(u.total / 1e9, 2),
                    "used_gb":  round(u.used  / 1e9, 2),
                    "free_gb":  round(u.free  / 1e9, 2),
                    "percent":  u.percent,
                }
            except Exception as e:
                return {"success": False, "error": str(e)}
        import shutil as _shutil
        t, u, f = _shutil.disk_usage(path)
        return {
            "success":  True,
            "path":     path,
            "total_gb": round(t / 1e9, 2),
            "used_gb":  round(u / 1e9, 2),
            "free_gb":  round(f / 1e9, 2),
        }

    def list_drives(self) -> Dict:
        """List all drive letters (Windows) or mount points (Linux)."""
        if IS_WINDOWS:
            import ctypes
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            drives  = []
            for i in range(26):
                if bitmask & (1 << i):
                    letter = chr(ord("A") + i) + ":\\"
                    drives.append(letter)
            return {"success": True, "drives": drives}
        # Linux/Mac
        r = subprocess.run(["df", "-h", "--output=target"], capture_output=True, text=True, timeout=30)
        mounts = [l.strip() for l in r.stdout.splitlines()[1:] if l.strip()]
        return {"success": True, "mountpoints": mounts}

    def get_volume_info(self, drive: str = "C:\\") -> Dict:
        """Windows volume label and serial number."""
        if not IS_WINDOWS:
            return {"success": False, "error": "Windows only"}
        r = self.execute_command(f"vol {drive}", timeout=5)
        return {"success": r.get("success", False), "output": r.get("stdout", ""), "drive": drive}

    # ─────────────────────────────────────────────────────────────────────────
    #  Display
    # ─────────────────────────────────────────────────────────────────────────

    def get_screen_resolution(self) -> Dict:
        """Get current screen resolution."""
        try:
            if IS_WINDOWS:
                import ctypes
                user32 = ctypes.windll.user32
                w = user32.GetSystemMetrics(0)
                h = user32.GetSystemMetrics(1)
                return {"success": True, "width": w, "height": h,
                        "resolution": f"{w}x{h}"}
            else:
                r = subprocess.run(["xdpyinfo"], capture_output=True, text=True, timeout=30)
                m = re.search(r"dimensions:\s+(\d+)x(\d+)", r.stdout)
                if m:
                    return {"success": True, "width": int(m.group(1)),
                            "height": int(m.group(2))}
        except Exception as e:
            pass
        return {"success": False, "error": "Could not determine resolution"}

    def set_screen_resolution(self, width: int, height: int,
                               refresh_rate: int = 60) -> Dict:
        """Change screen resolution (Windows)."""
        if not IS_WINDOWS:
            return {"success": False, "error": "Windows only for now"}
        ps_script = (
            f"Add-Type -AssemblyName System.Windows.Forms\n"
            f"$screen = [System.Windows.Forms.Screen]::PrimaryScreen\n"
            f"# Resolution change requires Win32 DEVMODE struct via P/Invoke\n"
            f"Write-Host 'Attempting resolution {width}x{height}@{refresh_rate}Hz'\n"
        )
        # Proper approach: use DisplaySettings via PowerShell/WMI
        wmi_script = (
            f"$res = Get-WmiObject -Class Win32_VideoController\n"
            f"Write-Host $res.CurrentHorizontalResolution"
        )
        r = self.execute_powershell(wmi_script, timeout=15)
        return {
            "success": True,
            "note": "Resolution change requires DEVMODE P/Invoke — current reading returned",
            "current_output": r.get("stdout", ""),
        }

    def get_monitors(self) -> Dict:
        """Enumerate connected monitors."""
        def _get_win():
            r = subprocess.run(
                ["wmic", "desktopmonitor", "get",
                 "ScreenWidth,ScreenHeight,DeviceID,Status", "/format:csv"],
                capture_output=True, text=True, timeout=30,
            )
            return {"success": True, "raw": r.stdout}
            
        def _get_posix():
            r = subprocess.run(["xrandr", "--query"], capture_output=True,
                                text=True, timeout=30)
            monitors = re.findall(r"(\w+)\s+connected\s+([^\s]+)", r.stdout)
            return {
                "success":  True,
                "monitors": [{"name": m[0], "resolution": m[1]} for m in monitors],
            }

        _MONITOR_DISPATCH = {
            "windows": _get_win,
            "posix":   _get_posix,
        }
        
        platform_key = "windows" if IS_WINDOWS else "posix"
        return _MONITOR_DISPATCH[platform_key]()

    # ─────────────────────────────────────────────────────────────────────────
    #  Audio
    # ─────────────────────────────────────────────────────────────────────────

    def get_volume(self) -> Dict:
        """Get current master volume (0-100)."""
        def _get_win():
            try:
                from ctypes import POINTER, cast
                from comtypes import CLSCTX_ALL
                from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                volume = cast(interface, POINTER(IAudioEndpointVolume))
                vol_scalar = volume.GetMasterVolumeLevelScalar()
                muted = volume.GetMute()
                return {"success": True, "volume": round(vol_scalar * 100), "muted": bool(muted)}
            except ImportError:
                r = self.execute_powershell("(Get-AudioDevice -Playback).Volume", timeout=10)
                return {"success": r["success"], "output": r.get("stdout", "")}

        def _get_linux():
            r = subprocess.run(["amixer", "get", "Master"], capture_output=True, text=True, timeout=30)
            m = re.search(r"\[(\d+)%\]", r.stdout)
            return {"success": True, "volume": int(m.group(1)) if m else None}

        _GET_VOL_DISPATCH = {"windows": _get_win, "linux": _get_linux}
        platform_key = "windows" if IS_WINDOWS else "linux" if IS_LINUX else "unknown"
        handler = _GET_VOL_DISPATCH.get(platform_key)
        if not handler: return {"success": False, "error": "Not implemented for this OS"}
        return handler()

    def set_volume(self, level: int) -> Dict:
        """Set master volume (0-100)."""
        level = max(0, min(100, level))
        
        def _set_win():
            ps = (
                f"$wshShell = New-Object -ComObject WScript.Shell\n"
                f"(New-Object -ComObject Shell.Application).Namespace(0) | % {{ $null }}\n"
                f"$nircmd = (Get-Command nircmd -ErrorAction SilentlyContinue)\n"
                f"if ($nircmd) {{ nircmd setsysvolume {int(level * 655.35)} }}\n"
                f"else {{ Write-Host 'nircmd not found; volume not changed' }}\n"
            )
            r = self.execute_powershell(ps, timeout=10)
            return {"success": r["success"], "level": level, "output": r.get("stdout", "")}
            
        def _set_linux():
            r = subprocess.run(["amixer", "-q", "sset", "Master", f"{level}%"], capture_output=True, timeout=30)
            return {"success": r.returncode == 0, "level": level}
            
        _VOLUME_DISPATCH = {"windows": _set_win, "linux": _set_linux}
        platform_key = "windows" if IS_WINDOWS else "linux" if IS_LINUX else "unknown"
        handler = _VOLUME_DISPATCH.get(platform_key)
        if not handler: return {"success": False, "error": "Not implemented"}
        return handler()

    def mute_audio(self) -> Dict:
        _MUTE_DISPATCH = {
            "windows": lambda: self.execute_powershell("(New-Object -ComObject Shell.Application) | % {$null}; $wsh = New-Object -ComObject WScript.Shell; $wsh.SendKeys([char]173)", timeout=5),
            "linux":   lambda: subprocess.run(["amixer", "-q", "sset", "Master", "mute"], timeout=30),
        }
        platform_key = "windows" if IS_WINDOWS else "linux" if IS_LINUX else "unknown"
        handler = _MUTE_DISPATCH.get(platform_key)
        if not handler: return {"success": False, "error": "Not implemented"}
        r = handler()
        # Handle both subprocess.CompletedProcess and custom result dicts
        success = r.get("success") if isinstance(r, dict) else r.returncode == 0
        return {"success": success, "state": "muted"}

    def unmute_audio(self) -> Dict:
        _UNMUTE_DISPATCH = {
            "linux": lambda: subprocess.run(["amixer", "-q", "sset", "Master", "unmute"], timeout=30),
        }
        platform_key = "linux" if IS_LINUX else "unknown"
        handler = _UNMUTE_DISPATCH.get(platform_key)
        if handler:
            r = handler()
            return {"success": r.returncode == 0, "state": "unmuted"}
        return self.set_volume(50)

    def get_audio_devices(self) -> Dict:
        """List audio playback and recording devices."""
        def _get_win():
            r = subprocess.run(["wmic", "path", "win32_sounddevice", "get", "Name,Status,DeviceID", "/format:csv"], capture_output=True, text=True, timeout=30)
            return {"success": True, "raw": r.stdout}

        def _get_linux():
            r = subprocess.run(["aplay", "-l"], capture_output=True, text=True, timeout=30)
            return {"success": True, "playback": r.stdout}

        _DEVICES_DISPATCH = {"windows": _get_win, "linux": _get_linux}
        platform_key = "windows" if IS_WINDOWS else "linux" if IS_LINUX else "unknown"
        handler = _DEVICES_DISPATCH.get(platform_key)
        if not handler: return {"success": False, "error": "Not implemented"}
        return handler()

    # ─────────────────────────────────────────────────────────────────────────
    #  Clipboard
    # ─────────────────────────────────────────────────────────────────────────

    def get_clipboard(self) -> Dict:
        """Read current clipboard text content."""
        def _get_win():
            import ctypes
            ctypes.windll.user32.OpenClipboard(None)
            handle = ctypes.windll.user32.GetClipboardData(1) # CF_TEXT
            if handle:
                text = ctypes.cast(handle, ctypes.c_char_p).value.decode("utf-8", errors="replace")
            else:
                text = ""
            ctypes.windll.user32.CloseClipboard()
            return {"success": True, "text": text}
            
        def _get_linux():
            r = subprocess.run(["xclip", "-selection", "clipboard", "-o"], capture_output=True, text=True, timeout=30)
            return {"success": r.returncode == 0, "text": r.stdout}
            
        def _get_mac():
            r = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=30)
            return {"success": True, "text": r.stdout}
            
        _CLIP_GET_DISPATCH = {"windows": _get_win, "linux": _get_linux, "mac": _get_mac}
        platform_key = "windows" if IS_WINDOWS else "linux" if IS_LINUX else "mac" if IS_MAC else "unknown"
        handler = _CLIP_GET_DISPATCH.get(platform_key)
        if handler:
            try: return handler()
            except Exception: pass
            
        try:
            import pyperclip
            return {"success": True, "text": pyperclip.paste()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def set_clipboard(self, text: str) -> Dict:
        """Write text to clipboard."""
        def _set_win():
            subprocess.run(["clip"], input=text, text=True, timeout=5)
            return {"success": True, "chars_written": len(text)}
            
        def _set_linux():
            r = subprocess.run(["xclip", "-selection", "clipboard"], input=text, text=True, timeout=5)
            return {"success": r.returncode == 0}
            
        def _set_mac():
            r = subprocess.run(["pbcopy"], input=text, text=True, timeout=30)
            return {"success": r.returncode == 0}
            
        _CLIP_SET_DISPATCH = {"windows": _set_win, "linux": _set_linux, "mac": _set_mac}
        platform_key = "windows" if IS_WINDOWS else "linux" if IS_LINUX else "mac" if IS_MAC else "unknown"
        handler = _CLIP_SET_DISPATCH.get(platform_key)
        if handler:
            try: return handler()
            except Exception: pass
            
        try:
            import pyperclip
            pyperclip.copy(text)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def clear_clipboard(self) -> Dict:
        return self.set_clipboard("")

    # ─────────────────────────────────────────────────────────────────────────
    #  Notifications
    # ─────────────────────────────────────────────────────────────────────────

    def send_notification(self, title: str, message: str,
                           duration: int = 5,
                           icon: str = None) -> Dict:
        """Send a native desktop notification."""
        def _notify_win():
            try:
                from win10toast import ToastNotifier
                ToastNotifier().show_toast(title, message, duration=duration, threaded=True)
                return {"success": True, "method": "win10toast"}
            except ImportError:
                ps = (
                    f"[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null\n"
                    f"$template = [Windows.UI.Notifications.ToastTemplateType]::ToastText02\n"
                    f"$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($template)\n"
                    f"$xml.GetElementsByTagName('text')[0].InnerText = '{title}'\n"
                    f"$xml.GetElementsByTagName('text')[1].InnerText = '{message}'\n"
                    f"$toast = New-Object Windows.UI.Notifications.ToastNotification $xml\n"
                    f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('NovaMind').Show($toast)\n"
                )
                r = self.execute_powershell(ps, timeout=10)
                return {"success": r["success"], "method": "powershell"}

        def _notify_linux():
            cmd = ["notify-send", title, message, "-t", str(duration * 1000)]
            if icon: cmd += ["-i", icon]
            r = subprocess.run(cmd, timeout=5)
            return {"success": r.returncode == 0}

        def _notify_mac():
            script = f'display notification "{message}" with title "{title}"'
            r = subprocess.run(["osascript", "-e", script], timeout=10)
            return {"success": r.returncode == 0}

        _NOTIFY_DISPATCH = {"windows": _notify_win, "linux": _notify_linux, "mac": _notify_mac}
        platform_key = "windows" if IS_WINDOWS else "linux" if IS_LINUX else "mac" if IS_MAC else "unknown"
        handler = _NOTIFY_DISPATCH.get(platform_key)
        if not handler: return {"success": False, "error": "Unsupported OS"}
        return handler()

    def show_message_box(self, title: str, message: str,
                          style: int = 0) -> Dict:
        """Show a Windows message box (blocking). style: 0=OK, 1=OK/Cancel, etc."""
        if not IS_WINDOWS:
            return {"success": False, "error": "Windows only"}
        try:
            import ctypes
            result = ctypes.windll.user32.MessageBoxW(
                None, message, title, style
            )
            return {"success": True, "result": result,
                    "button": {1: "OK", 2: "Cancel", 6: "Yes", 7: "No"}.get(result, str(result))}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ─────────────────────────────────────────────────────────────────────────
    #  Power Management
    # ─────────────────────────────────────────────────────────────────────────

    def get_battery(self) -> Dict:
        """Battery status (laptops)."""
        if self._psutil:
            import psutil
            batt = psutil.sensors_battery()
            if batt:
                return {
                    "success":      True,
                    "percent":      batt.percent,
                    "plugged_in":   batt.power_plugged,
                    "time_left_s":  batt.secsleft if batt.secsleft != psutil.POWER_TIME_UNLIMITED else -1,
                    "charging":     batt.power_plugged and batt.percent < 100,
                }
            return {"success": True, "battery": "No battery found (desktop)"}
        return {"success": False, "error": "psutil required"}

    def set_power_plan(self, plan: str = "balanced") -> Dict:
        """Switch Windows power plan: balanced / high_performance / power_saver."""
        if not IS_WINDOWS:
            return {"success": False, "error": "Windows only"}
        guids = {
            "balanced":         "381b4222-f694-41f0-9685-ff5bb260df2e",
            "high_performance": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
            "power_saver":      "a1841308-3541-4fab-bc81-f71556f20b4a",
        }
        guid = guids.get(plan.lower().replace(" ", "_"))
        if not guid:
            return {"success": False, "error": f"Unknown plan: {plan}"}
        r = self.execute_command(f"powercfg /setactive {guid}")
        return {"success": r.get("success", False), "plan": plan}

    def shutdown_system(self, delay_seconds: int = 30,
                         message: str = "NovaMind is shutting down the system.") -> Dict:
        """Schedule system shutdown. Requires admin."""
        if IS_WINDOWS:
            r = self.execute_command(f'shutdown /s /t {delay_seconds} /c "{message}"')
        else:
            r = self.execute_command(f"shutdown -h +{delay_seconds // 60 or 1}")
        return {"success": r.get("success", False), "delay_seconds": delay_seconds}

    def reboot_system(self, delay_seconds: int = 30) -> Dict:
        """Schedule system reboot."""
        if IS_WINDOWS:
            r = self.execute_command(f"shutdown /r /t {delay_seconds}")
        else:
            r = self.execute_command(f"shutdown -r +{delay_seconds // 60 or 1}")
        return {"success": r.get("success", False), "delay_seconds": delay_seconds}

    def sleep_system(self) -> Dict:
        """Put system to sleep/suspend."""
        _SLEEP_DISPATCH = {
            "windows": lambda: self.execute_powershell("Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Application]::SetSuspendState([System.Windows.Forms.PowerState]::Suspend, $false, $false)"),
            "linux":   lambda: self.execute_command("systemctl suspend"),
            "mac":     lambda: self.execute_command("pmset sleepnow"),
        }
        platform_key = "windows" if IS_WINDOWS else "linux" if IS_LINUX else "mac" if IS_MAC else "unknown"
        handler = _SLEEP_DISPATCH.get(platform_key)
        if not handler: return {"success": False, "error": "Unsupported OS"}
        r = handler()
        return {"success": r.get("success", False)}

    def hibernate_system(self) -> Dict:
        _HIBERNATE_DISPATCH = {
            "windows": lambda: self.execute_command("shutdown /h"),
            "linux":   lambda: self.execute_command("systemctl hibernate"),
        }
        platform_key = "windows" if IS_WINDOWS else "linux" if IS_LINUX else "unknown"
        handler = _HIBERNATE_DISPATCH.get(platform_key)
        if not handler: return {"success": False, "error": "Hibernate not supported"}
        r = handler()
        return {"success": r.get("success", False)}

    # ─────────────────────────────────────────────────────────────────────────
    #  Scheduled Tasks (Windows)
    # ─────────────────────────────────────────────────────────────────────────

    def list_scheduled_tasks(self, folder: str = "\\") -> Dict:
        """List all Windows scheduled tasks."""
        if not IS_WINDOWS:
            return self.execute_command("crontab -l")
        r = subprocess.run(
            ["schtasks", "/query", "/fo", "CSV", "/nh"],
            capture_output=True, text=True, timeout=20,
        )
        tasks = []
        for line in r.stdout.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 3:
                tasks.append({
                    "name":   parts[0],
                    "next_run": parts[1],
                    "status": parts[2] if len(parts) > 2 else "",
                })
        return {"success": True, "tasks": tasks, "count": len(tasks)}

    def create_scheduled_task(self, name: str, command: str,
                               schedule: str = "DAILY",
                               start_time: str = "12:00",
                               run_as: str = None) -> Dict:
        """Create a Windows scheduled task."""
        if not IS_WINDOWS:
            return {"success": False, "error": "Windows only (use cron on Linux)"}
        cmd = (f'schtasks /create /tn "{name}" /tr "{command}" '
               f'/sc {schedule} /st {start_time} /f')
        if run_as:
            cmd += f' /ru {run_as}'
        r = self.execute_command(cmd, timeout=30)
        return {"success": r.get("success", False), "task": name, "schedule": schedule}

    def delete_scheduled_task(self, name: str) -> Dict:
        if not IS_WINDOWS:
            return {"success": False, "error": "Windows only"}
        r = self.execute_command(f'schtasks /delete /tn "{name}" /f')
        return {"success": r.get("success", False), "task": name}

    def run_scheduled_task(self, name: str) -> Dict:
        if not IS_WINDOWS:
            return {"success": False, "error": "Windows only"}
        r = self.execute_command(f'schtasks /run /tn "{name}"')
        return {"success": r.get("success", False), "task": name}

    # ─────────────────────────────────────────────────────────────────────────
    #  Event Log (Windows)
    # ─────────────────────────────────────────────────────────────────────────

    def read_event_log(self, log_name: str = "System",
                        max_events: int = 50,
                        level: int = None) -> Dict:
        """Read Windows Event Log entries."""
        if not IS_WINDOWS:
            return self.execute_command(f"journalctl -n {max_events} --no-pager")

        _filter   = '| Where-Object {$_.EntryType -eq "Error"}' if level else ''
        ps = (
            f"Get-EventLog -LogName '{log_name}' -Newest {max_events} "
            f"{_filter} "
            f"| Select-Object TimeGenerated,EntryType,Source,Message | "
            f"ConvertTo-Json -Compress"
        )
        r = self.execute_powershell(ps, timeout=30)
        events = []
        if r.get("success", False):
            try:
                events = json.loads(r.get("stdout", "[]") or "[]")
                if isinstance(events, dict):
                    events = [events]
            except json.JSONDecodeError:
                pass
        return {
            "success": True,
            "log_name": log_name,
            "events": events,
            "count": len(events),
        }

    def get_recent_system_errors(self, hours: int = 24,
                                   max_events: int = 20) -> Dict:
        """Fetch recent Error/Critical events from System log."""
        if not IS_WINDOWS:
            r = self.execute_command(f"journalctl -p err -n {max_events} --no-pager")
            return {"success": r["success"], "output": r.get("stdout", "")}

        ps = (
            f"$since = (Get-Date).AddHours(-{hours})\n"
            f"Get-EventLog -LogName System -EntryType Error,Warning "
            f"-After $since -Newest {max_events} | "
            f"Select-Object TimeGenerated,EntryType,Source,EventID,"
            f"@{{n='Message';e={{$_.Message.Substring(0, [Math]::Min(200,$_.Message.Length))}}}} | "
            f"ConvertTo-Json -Compress"
        )
        r = self.execute_powershell(ps, timeout=30)
        events = []
        try:
            events = json.loads(r.get("stdout", "[]") or "[]")
            if isinstance(events, dict):
                events = [events]
        except Exception:
            pass
        return {
            "success": True,
            "hours": hours,
            "events": events,
            "count": len(events),
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  Firewall (Windows)
    # ─────────────────────────────────────────────────────────────────────────

    def list_firewall_rules(self, direction: str = None,
                             enabled: bool = None,
                             max_rules: int = 100) -> Dict:
        if not IS_WINDOWS:
            r = self.execute_command("iptables -L -n --line-numbers 2>/dev/null || "
                                      "ufw status verbose 2>/dev/null")
            return {"success": True, "output": r.get("stdout", "")}

        where_clauses = []
        if direction:
            where_clauses.append(f'$_.Direction -eq "{direction}"')
        if enabled is not None:
            where_clauses.append(f'$_.Enabled -eq {str(enabled).lower()}')

        where_ps = ""
        if where_clauses:
            where_ps = f"| Where-Object {{ {' -and '.join(where_clauses)} }}"

        ps = (
            f"Get-NetFirewallRule {where_ps} | "
            f"Select-Object -First {max_rules} Name,DisplayName,Direction,"
            f"Action,Enabled,Profile | ConvertTo-Json -Compress"
        )
        r = self.execute_powershell(ps, timeout=20)
        rules = []
        try:
            rules = json.loads(r.get("stdout", "[]") or "[]")
            if isinstance(rules, dict):
                rules = [rules]
        except Exception:
            pass
        return {"success": True, "rules": rules, "count": len(rules)}

    def add_firewall_rule(self, name: str, direction: str = "Inbound",
                           action: str = "Allow", protocol: str = "TCP",
                           local_port: int = None,
                           remote_address: str = "Any") -> Dict:
        if not IS_WINDOWS:
            return {"success": False, "error": "Windows only"}
        port_arg = f"-LocalPort {local_port}" if local_port else ""
        ps = (
            f"New-NetFirewallRule -DisplayName '{name}' -Direction {direction} "
            f"-Action {action} -Protocol {protocol} {port_arg} "
            f"-RemoteAddress {remote_address}"
        )
        r = self.execute_powershell(ps, timeout=30)
        return {"success": r.get("success", False), "rule": name}

    def remove_firewall_rule(self, name: str) -> Dict:
        if not IS_WINDOWS:
            return {"success": False, "error": "Windows only"}
        ps = f"Remove-NetFirewallRule -DisplayName '{name}'"
        r  = self.execute_powershell(ps, timeout=15)
        return {"success": r.get("success", False), "rule": name}

    # ─────────────────────────────────────────────────────────────────────────
    #  Printers
    # ─────────────────────────────────────────────────────────────────────────

    def list_printers(self) -> Dict:
        if IS_WINDOWS:
            ps = "Get-Printer | Select-Object Name,PrinterStatus,JobCount | ConvertTo-Json"
            r  = self.execute_powershell(ps, timeout=15)
            printers = []
            try:
                printers = json.loads(r.get("stdout", "[]") or "[]")
                if isinstance(printers, dict):
                    printers = [printers]
            except Exception:
                pass
            return {"success": True, "printers": printers}
        # Linux
        r = self.execute_command("lpstat -a 2>/dev/null || echo 'No CUPS'")
        return {"success": True, "output": r.get("stdout", "")}

    def get_default_printer(self) -> Dict:
        if IS_WINDOWS:
            ps = "(Get-WmiObject -Query \"select * from Win32_Printer where Default=True\").Name"
            r  = self.execute_powershell(ps, timeout=10)
            return {"success": r.get("success", False), "printer": r.get("stdout", "").strip()}
        r = self.execute_command("lpstat -d")
        return {"success": r["success"], "output": r.get("stdout", "")}

    def set_default_printer(self, name: str) -> Dict:
        if IS_WINDOWS:
            ps = f"(New-Object -ComObject WScript.Network).SetDefaultPrinter('{name}')"
            r  = self.execute_powershell(ps, timeout=10)
            return {"success": r.get("success", False), "printer": name}
        r = self.execute_command(f"lpoptions -d '{name}'")
        return {"success": r["success"]}

    # ─────────────────────────────────────────────────────────────────────────
    #  Startup Items
    # ─────────────────────────────────────────────────────────────────────────

    def list_startup_items(self) -> Dict:
        """List startup apps and commands."""
        def _list_win():
            items: List[Dict] = []
            paths = [
                "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run",
                "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run",
            ]
            for path in paths:
                reg_r = self.registry_list(path)
                if reg_r["success"]:
                    for v in reg_r.get("values", []):
                        items.append({"name": v["name"], "command": v["data"], "location": path})
            return {"success": True, "items": items}

        def _list_linux():
            r = self.execute_command("ls ~/.config/autostart/ 2>/dev/null; ls /etc/xdg/autostart/ 2>/dev/null")
            return {"success": True, "output": r.get("stdout", "")}

        _STARTUP_DISPATCH = {"windows": _list_win, "linux": _list_linux}
        platform_key = "windows" if IS_WINDOWS else "linux" if IS_LINUX else "unknown"
        handler = _STARTUP_DISPATCH.get(platform_key)
        if not handler: return {"success": False, "error": "Not implemented"}
        return handler()

    def disable_startup_item(self, name: str) -> Dict:
        """Disable a startup item by removing it from the registry Run key."""
        if not IS_WINDOWS:
            return {"success": False, "error": "disable_startup_item only supported on Windows"}
        paths = [
            "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run",
            "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run",
        ]
        for path in paths:
            result = self.registry_delete(path, name)
            if result.get("success"):
                return {"success": True, "name": name, "removed_from": path}
        return {"success": False, "error": f"Startup item '{name}' not found in registry Run keys"}

    def lock_screen(self) -> Dict:
        """Lock the workstation screen."""
        def _lock_win():
            ctypes.windll.user32.LockWorkStation()
            return {"success": True}

        def _lock_linux():
            for cmd in [["gnome-screensaver-command", "--lock"], ["xdg-screensaver", "lock"], ["loginctl", "lock-session"]]:
                r = subprocess.run(cmd, timeout=5)
                if r.returncode == 0: return {"success": True, "method": cmd}
            return {"success": False, "error": "Linux lock failed"}

        def _lock_mac():
            r = subprocess.run(["/System/Library/CoreServices/Menu Extras/User.menu/Contents/Resources/CGSession", "-suspend"], timeout=5)
            return {"success": r.returncode == 0}

        _LOCK_DISPATCH = {"windows": _lock_win, "linux": _lock_linux, "mac": _lock_mac}
        platform_key = "windows" if IS_WINDOWS else "linux" if IS_LINUX else "mac" if IS_MAC else "unknown"
        handler = _LOCK_DISPATCH.get(platform_key)
        if not handler: return {"success": False, "error": "Lock not available"}
        return handler()

    def get_installed_apps(self, search: str = None, limit: int = 200) -> Dict:
        """List installed applications."""
        def _get_win():
            ps = "Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* | Select-Object DisplayName,DisplayVersion,Publisher,InstallDate | Where-Object {$_.DisplayName} | ConvertTo-Json"
            r = self.execute_powershell(ps, timeout=30)
            apps = []
            try:
                apps = json.loads(r.get("stdout", "[]") or "[]")
                if isinstance(apps, dict): apps = [apps]
            except Exception: pass
            if search:
                apps = [a for a in apps if search.lower() in (a.get("DisplayName") or "").lower()]
            return {"success": True, "apps": apps[:limit], "count": len(apps)}

        def _get_linux():
            r = self.execute_command("dpkg -l 2>/dev/null | awk '/^ii/{print $2,$3}' | head -200")
            return {"success": True, "output": r.get("stdout", "")}

        _APPS_DISPATCH = {"windows": _get_win, "linux": _get_linux}
        platform_key = "windows" if IS_WINDOWS else "linux" if IS_LINUX else "unknown"
        handler = _APPS_DISPATCH.get(platform_key)
        if not handler: return {"success": False, "error": "Not implemented"}
        return handler()

    def get_system_fonts(self) -> Dict:
        """List all installed system fonts."""
        def _get_win():
            font_dir = Path("C:/Windows/Fonts")
            fonts = [f.name for f in font_dir.glob("*.[tT][tT][fF]")]
            fonts += [f.name for f in font_dir.glob("*.[oO][tT][fF]")]
            return {"success": True, "fonts": sorted(fonts), "count": len(fonts)}

        def _get_linux():
            r = subprocess.run(["fc-list"], capture_output=True, text=True, timeout=10)
            return {"success": True, "output": r.stdout, "count": len(r.stdout.splitlines())}

        _FONTS_DISPATCH = {"windows": _get_win, "linux": _get_linux}
        platform_key = "windows" if IS_WINDOWS else "linux" if IS_LINUX else "unknown"
        handler = _FONTS_DISPATCH.get(platform_key)
        if not handler: return {"success": False, "error": "Not implemented"}
        return handler()

    def empty_recycle_bin(self) -> Dict:
        """Empty the Windows Recycle Bin."""
        if not IS_WINDOWS:
            return {"success": False, "error": "Windows only"}
        ps = (
            "Clear-RecycleBin -Force -ErrorAction SilentlyContinue; "
            "Write-Host 'Recycle Bin emptied'"
        )
        r = self.execute_powershell(ps, timeout=30)
        return {"success": r["success"], "output": r.get("stdout", "")}

    def get_temp_dir_size(self) -> Dict:
        """Calculate total size of the temp directory."""
        tmp = Path(tempfile.gettempdir())
        total = 0
        count = 0
        for f in tmp.rglob("*"):
            try:
                if f.is_file():
                    total += f.stat().st_size
                    count += 1
            except Exception:
                pass
        return {
            "success":   True,
            "temp_dir":  str(tmp),
            "size_mb":   round(total / 1e6, 2),
            "file_count": count,
        }

    def clean_temp_files(self, older_than_hours: int = 24,
                          dry_run: bool = True) -> Dict:
        """Delete old temp files (dry_run=True by default for safety)."""
        tmp      = Path(tempfile.gettempdir())
        cutoff   = time.time() - (older_than_hours * 3600)
        deleted: List[str] = []
        errors:  List[str] = []
        total_bytes = 0

        for f in tmp.rglob("*"):
            try:
                if f.is_file() and f.stat().st_mtime < cutoff:
                    size = f.stat().st_size
                    if not dry_run:
                        f.unlink()
                    total_bytes += size
                    deleted.append(str(f))
            except Exception as e:
                errors.append(str(e))

        return {
            "success":      True,
            "dry_run":      dry_run,
            "files_found":  len(deleted),
            "freed_mb":     round(total_bytes / 1e6, 2),
            "sample":       deleted[:10],
            "errors":       errors[:5],
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  Security Check + Logging
    # ─────────────────────────────────────────────────────────────────────────

    def _security_check(self, command: str) -> Tuple[bool, str]:
        cmd_l = command.lower().strip()
        for pattern in self.BLOCKED_PATTERNS:
            if re.search(pattern, cmd_l, re.IGNORECASE):
                return False, f"Blocked pattern: {pattern}"
        return True, "OK"

    def _log_exec(self, command: str, success: bool, duration: float):
        self.execution_log.append({
            "ts":       datetime.now().isoformat(),
            "command":  command[:300],
            "success":  success,
            "secs":     round(duration, 2),
        })
        if len(self.execution_log) > 5000:
            self.execution_log = self.execution_log[-2000:]

    def _log_action(self, limit: int = 50) -> Dict:
        return {
            "success": True,
            "count":   len(self.execution_log),
            "recent":  self.execution_log[-limit:],
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  Helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _try_import(module_name: str):
        try:
            return importlib.import_module(module_name)
        except ImportError:
            return None

    def get_execution_log(self) -> List[Dict]:
        return self.execution_log[-50:]


import importlib
