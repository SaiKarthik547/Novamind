#!/usr/bin/env python3
"""
NovaMind - Autonomous Desktop AI Agent
Eyes → Brain → Hands Architecture
Main entry point — wires all components together.
"""
import json
import logging
import logging.handlers
import os
import sys
import io
import time
import threading
import argparse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.runtime_paths import ensure_runtime_dir, get_runtime_root, runtime_path

# ERROR 1 FIX: Force UTF-8 on Windows console before any logger calls.
# Windows PowerShell defaults to CP1252 which cannot encode ✓ ✗ → etc.
_WRAP_UTF8 = lambda s: io.TextIOWrapper(s.buffer, encoding="utf-8", errors="replace")
_KEEP = lambda s: s

_APPLY_UTF8: Dict[bool,callable] = {
    True: _WRAP_UTF8,
    False: _KEEP
}

sys.stdout = _APPLY_UTF8[
    hasattr(sys.stdout, "buffer") and getattr(sys.stdout, "encoding", "").lower() != "utf-8"
](sys.stdout)

sys.stderr = _APPLY_UTF8[
    hasattr(sys.stderr, "buffer") and getattr(sys.stderr, "encoding", "").lower() != "utf-8"
](sys.stderr)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.log_manager import setup_structured_logging, get_logger

# ── Logging ──────────────────────────────────────────────────────────────────
setup_structured_logging(str(runtime_path("logs")))
logger = get_logger("NovaMind")

__version__ = "3.0.0"


# ─────────────────────────────────────────────────────────────────────────────
#  Dependency check
# ─────────────────────────────────────────────────────────────────────────────

def check_dependencies() -> Dict[str, bool]:
    CHECKS = {
        "requests":              lambda: __import__("requests"),
        "pillow":                lambda: __import__("PIL"),
        "numpy":                 lambda: __import__("numpy"),
        "pytesseract":           lambda: __import__("pytesseract"),
        "easyocr":               lambda: __import__("easyocr"),
        "opencv":                lambda: __import__("cv2"),
        "sentence_transformers": lambda: __import__("sentence_transformers"),
        "psutil":                lambda: __import__("psutil"),
        "pyqt6":                 lambda: __import__("PyQt6"),
        "pyautogui":             lambda: __import__("pyautogui"),
        "pygetwindow":           lambda: __import__("pygetwindow"),
        "playwright":            lambda: __import__("playwright"),
        "selenium":              lambda: __import__("selenium"),
    }
    deps: Dict[str, bool] = {}
    for name, fn in CHECKS.items():
        try:
            fn()
            deps[name] = True
        except ImportError:
            deps[name] = False

    # Sprint 1.1: Register UIA type library automatically so comtypes.gen
    # has UIAutomationClient available on first run.
    if deps.get("comtypes", False) or True:   # always attempt — comtypes may not be in CHECKS
        try:
            import comtypes.client
            comtypes.client.GetModule("UIAutomationCore.dll")
            logger.debug("UIA type lib registered via UIAutomationCore.dll")
        except Exception:
            try:
                import comtypes.client
                comtypes.client.GetModule(("{ff48dba4-60ef-4201-aa87-54103eef594e}", 1, 0))
                logger.debug("UIA type lib registered via GUID")
            except Exception as _uia_err:
                logger.warning(f"UIA type lib registration failed: {_uia_err}")

    return deps


def print_banner() -> None:
    print(f"""
╔══════════════════════════════════════════════════════╗
║   NovaMind v{__version__} — Autonomous Desktop AI      ║
║   Eyes → Brain → Hands  (Multi-Agent Architecture)  ║
║   EventBus · VerifierAgent · ErrorRecoveryAgent      ║
╚══════════════════════════════════════════════════════╝""")


def load_env_keys() -> None:
    env_path = runtime_path(".env")
    try:
        env_lines = env_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    for line in env_lines:
        line = line.strip()
        try:
            k, v = line.split("=", 1)
        except ValueError:
            continue
        _dispatch = {
            (False, False): lambda: os.environ.setdefault(k.strip(), v.strip().strip('"\'')),
            (False, True): lambda: None,
            (True, False): lambda: None,
            (True, True): lambda: None,
        }
        _dispatch[(line.startswith("#"), not line)]()
    logger.info("Loaded API keys from %s", env_path)


# ─────────────────────────────────────────────────────────────────────────────
#  Application class
# ─────────────────────────────────────────────────────────────────────────────

class NovaMindApp:
    def __init__(self, headless: bool = False, no_game: bool = False):
        self.headless = headless
        self.no_game  = no_game
        self.deps     = check_dependencies()
        self.running  = False
        self.start_time = datetime.now()

        # Core components
        self.brain          = None
        self.vision         = None
        self.agents: Dict   = {}
        self.memory         = None
        self.security       = None
        self.scheduler      = None
        self.event_bus      = None
        self.state_manager  = None
        self.verifier       = None
        self.recovery_agent = None
        self.agent_registry_valid = False

        # Godot Ecosystem Components
        self.task_manager   = None
        self.bridge_server  = None
        self._bridge_thread = None

        # Optional UI
        self.ui   = None

    def initialize(self) -> bool:
        logger.info("Initialising NovaMind v3 ...")
        load_env_keys()

        if not self.deps.get("requests"):
            logger.error("requests is required: pip install requests")
            return False

        # Initialize Core Infrastructure
        from core.event_recorder import EventRecorder
        self.event_recorder = EventRecorder()

        # LLM Router
        logger.info("-> LLM Router")
        from core.llm_router import get_router
        router = get_router()
        status = router.get_status()
        logger.info(f"  {status['active_providers']} active provider(s)")

        # Memory (must be first — EventBus persists to it)
        logger.info("-> Memory System")
        try:
            from memory.memory_system import MemorySystem
            self.memory = MemorySystem()
            stats = self.memory.get_memory_stats()
            logger.info(f"  {stats['total_memories']} memories, "
                        f"{stats['total_tasks']} tasks stored")
        except Exception as exc:
            logger.warning(f"  Memory init failed: {exc}")

        # EventBus
        logger.info("-> EventBus")
        try:
            from core.event_bus import get_event_bus
            self.event_bus = get_event_bus(memory_system=self.memory)
            
            # Wire Event Recorder to EventBus (Full System Logging)
            def _log_event_bus(event: dict):
                # Only log standard events, ignoring high-freq updates unless necessary
                evt_type = event.get("type", "UNKNOWN")
                self.event_recorder.log_event(
                    event_type=evt_type,
                    source_runtime="Python",
                    severity="INFO",
                    payload=event
                )
            
            self.event_bus.subscribe("*", _log_event_bus)
            logger.info("  EventBus ready and wired to EventRecorder")
        except Exception as exc:
            logger.warning(f"  EventBus init failed: {exc}")

        # StateManager
        logger.info("-> StateManager")
        try:
            from core.state_manager import StateManager
            db_path = str(runtime_path("memory.db"))
            self.state_manager = StateManager(db_path=db_path)
            logger.info("  StateManager ready")
        except Exception as exc:
            logger.warning(f"  StateManager init failed: {exc}")

        # Security
        logger.info("-> Security Layer")
        try:
            from security.command_guard import CommandGuard
            self.security = CommandGuard()
            logger.info("  Security layer ready (frozenset O(1) blacklist)")
        except Exception as exc:
            logger.warning(f"  Security init failed: {exc}")

        # Vision
        if self.deps.get("pillow"):
            logger.info("-> Vision System")
            try:
                from vision.vision_system import VisionSystem
                self.vision = VisionSystem()
                logger.info("  Vision ready")
            except Exception as exc:
                logger.warning(f"  Vision init failed: {exc}")
        else:
            logger.warning("  Pillow not installed -- vision disabled")

        # Agents
        logger.info("-> Agents")
        self._init_agents()

        if self.vision and "vision_agent" not in self.agents:
            self.agents["vision_agent"] = self.vision
            logger.info("  [v] vision_agent (VisionSystem)")

        # VerifierAgent
        logger.info("-> VerifierAgent")
        try:
            from agents.verifier_agent import VerifierAgent
            self.verifier = VerifierAgent(
                memory_system=self.memory,
                event_bus=self.event_bus,
            )
            self.agents["verifier_agent"] = self.verifier
            logger.info("  VerifierAgent ready (isolated LLM context)")
        except Exception as exc:
            logger.warning(f"  VerifierAgent init failed: {exc}")

        # ErrorRecoveryAgent
        logger.info("-> ErrorRecoveryAgent")
        try:
            from agents.error_recovery_agent import ErrorRecoveryAgent
            self.recovery_agent = ErrorRecoveryAgent(
                event_bus=self.event_bus,
                memory_system=self.memory,
            )
            self.agents["error_recovery_agent"] = self.recovery_agent
            logger.info("  ErrorRecoveryAgent ready (strategy pattern dispatch)")
        except Exception as exc:
            logger.warning(f"  ErrorRecoveryAgent init failed: {exc}")

        # Brain (wired with all new components)
        logger.info("-> Brain")
        try:
            from core.brain import Brain
            self.brain = Brain(
                vision_system=self.vision,
                agents=self.agents,
                memory_system=self.memory,
                security=self.security,
                event_bus=self.event_bus,
                state_manager=self.state_manager,
                verifier=self.verifier,
                recovery_agent=self.recovery_agent,
            )
            logger.info("  Brain ready (state machine + EventBus + Verifier)")
        except Exception as exc:
            logger.error(f"  Brain init failed: {exc}")
            return False

        # Subscribe EventBus handlers for observability
        if self.event_bus:
            self._wire_event_subscriptions()

        # Godot Bridge & Task Manager
        logger.info("-> Ecosystem Components")
        try:
            from core.task_manager import TaskManager
            from core.bridge_server import BridgeServer
            from security.permission_manager import PermissionManager
            
            self.task_manager = TaskManager()
            self.bridge_server = BridgeServer()
            # Replace basic security with PermissionManager for OS actions
            self.os_permissions = PermissionManager()
            
            # Register mock bridge handler for testing Vertical Slice
            async def on_godot_command(data):
                event_type = data.get("event_type")
                payload = data.get("payload", {})
                logger.info(f"Godot Bridge Event Received: {event_type} - {payload}")
                
                if event_type == "USER_COMMAND_ISSUED":
                    text = payload.get("text", "").lower()
                    if "workspace" in text or "vscode" in text:
                        # 1. Queue Task
                        async def open_workspace():
                            # 2. Check Permission
                            approved = await self.os_permissions.request_permission("open_process", "code .")
                            if approved:
                                await self.bridge_server.send_message("STATE_UPDATE", "hologram_status", {"message": "Permission Granted. Opening Workspace...", "color": "yellow"})
                                # Launch VSCode asynchronously
                                import asyncio
                                proc = await asyncio.create_subprocess_shell("code .", cwd=os.path.dirname(os.path.abspath(__file__)))
                                await proc.wait()
                                await self.bridge_server.send_message("STATE_UPDATE", "hologram_status", {"message": "Workspace Active", "color": "green"})
                            else:
                                await self.bridge_server.send_message("STATE_UPDATE", "hologram_status", {"message": "Permission Denied by User", "color": "red"})
                        
                        self.task_manager.submit("Open Workspace", open_workspace)
                        
            self.bridge_server.register_handler("EVENT", on_godot_command)
            
            # 3. Wire EventBus to Godot using Threadsafe Dispatcher
            if self.event_bus:
                def _forward_to_godot(event: dict):
                    # Uses the thread-safe dispatcher so any thread can emit events safely
                    # Map generic event to strict EVENT_TYPE Enum if possible
                    # We will use AGENT_TOOL_CALL, etc.
                    event_type_str = event.get("type", "AGENT_TOOL_CALL").upper()
                    # Prepend AGENT_ if it's a task event to match Enum
                    if event_type_str in ["TASK_STARTED", "TASK_COMPLETED", "TASK_FAILED"]:
                        event_type_str = "AGENT_" + event_type_str
                    self.bridge_server.send_message_threadsafe("STATE_UPDATE", event_type_str, event)
                
                # Forward critical agent events to visualize in the spatial world
                events_to_forward = [
                    "task_started", "task_completed", "task_failed",
                    "tool_call_start", "tool_call_end", "tool_call_error"
                ]
                self.event_bus.subscribe_many(events_to_forward, _forward_to_godot)
                logger.info("  EventBus wired to BridgeServer (Threadsafe IPC)")
                
            # 4. Wire Authoritative Heartbeat Reconciliation
            if self.task_manager and self.bridge_server:
                def _get_authoritative_state():
                    # Return list of active task/agent IDs so Godot can cull orphaned holograms
                    active_tasks = []
                    for t_id, task in self.task_manager.tasks.items():
                        if task.status in ["running", "pending"]:
                            active_tasks.append(t_id)
                    return {"active_tasks": active_tasks}
                self.bridge_server.heartbeat_callback = _get_authoritative_state
            
            logger.info("  Task Manager and Bridge Server ready")
        except Exception as exc:
            logger.warning(f"  Bridge init failed: {exc}")

        # Scheduler
        logger.info("-> Task Scheduler")
        try:
            from core.scheduler import TaskScheduler
            self.scheduler = TaskScheduler(brain=self.brain, memory=self.memory)
            self.scheduler.start()
            logger.info("  Scheduler ready")
        except Exception as exc:
            logger.warning(f"  Scheduler init failed: {exc}")

        # UI (optional)
        def _init_ui():
            logger.info("-> Task UI")
            try:
                # Disabled PyQt6 TaskWindow as per user request to have single Game window
                self.ui = None
                self._qt_app = None
                logger.info("  UI disabled (using Game UI only)")
            except Exception as exc:
                logger.warning(f"  UI init failed: {exc}")

        def _ui_disabled_msg():
            logger.warning("  PyQt6 not installed -- UI disabled")

        _ui_logic = {
            (True, True):  _init_ui,
            (True, False): _ui_disabled_msg,
        }
        # Only initialize UI if game is not active or we explicitly passed --no-game
        _ui_logic.get((not self.headless and not getattr(self, "game", None), bool(self.deps.get("pyqt6"))), lambda: None)()

        # Validate Agent Registry (O(1) contract check)
        logger.info("-> Validating Agent Registry")
        self.agent_registry_valid = self._validate_agent_registry()
        _val_msg = {
            True:  lambda: logger.info("  Agent registry validated (all agents follow BaseAgent O(1) contract)"),
            False: lambda: logger.warning("  Agent registry validation partial — some agents may use legacy dispatch"),
        }
        _val_msg[self.agent_registry_valid]()

        logger.info(
            f"NovaMind v{__version__} ready -- "
            f"{len(self.agents)} agents, "
            f"EventBus={'[v]' if self.event_bus else '[x]'}, "
            f"Verifier={'[v]' if self.verifier else '[x]'}, "
            f"Recovery={'[v]' if self.recovery_agent else '[x]'}"
        )
        return True

    # ──────────────────────────────────────────────────────────────────────────
    #  Agent initialisation
    # ──────────────────────────────────────────────────────────────────────────

    def _init_agents(self) -> None:
        AGENT_CLASSES = {
            "file_agent":        ("agents.file_agent",        "FileAgent"),
            "system_agent":      ("agents.system_agent",      "SystemAgent"),
            "browser_agent":     ("agents.browser_agent",     "BrowserAgent"),
            "code_agent":        ("agents.code_agent",        "CodeAgent"),
            "error_handler":     ("agents.error_handler",     "ErrorHandler"),
            "application_agent": ("agents.application_agent", "ApplicationAgent"),
            "network_agent":     ("agents.network_agent",     "NetworkAgent"),
            "memory_agent":      ("agents.memory_agent",      "MemoryAgent"),
            "data_agent":        ("agents.data_agent",        "DataAgent"),
            "email_agent":       ("agents.email_agent",       "EmailAgent"),
        }
        
        # Dependency map for agent instantiation (zero if-elif)
        DEPS_MAP = {
            "SystemAgent": {"event_bus": self.event_bus},
            "MemoryAgent": {"memory_system": self.memory},
        }

        for name, (module, cls_name) in AGENT_CLASSES.items():
            try:
                mod = __import__(module, fromlist=[cls_name])
                cls = getattr(mod, cls_name)
                
                # O(1) dependency lookup
                kwargs = DEPS_MAP.get(cls_name, {})
                self.agents[name] = cls(**kwargs)
                
                logger.info(f"  [v] {name}")
            except Exception as exc:
                logger.warning(f"  [x] {name}: {exc}")
        logger.info(f"  {len(self.agents)} core agents active")

    def _validate_agent_registry(self) -> bool:
        """
        Verify that all registered agents adhere to the BaseAgent O(1) contract.
        Checks:
          1. Agent is an instance of BaseAgent
          2. Agent has a non-empty handlers dict
          3. Agent does NOT have a local execute() method (should use base class)
        """
        from core.base_agent import BaseAgent
        all_valid = True
        for name, agent in self.agents.items():
            # VisionSystem might not be a BaseAgent yet (legacy)
            if name == "vision_agent": continue
            
            is_base = isinstance(agent, BaseAgent)
            has_handlers = hasattr(agent, "handlers") and isinstance(agent.handlers, dict)
            
            # Check for local execute method override (we want the BaseAgent.execute)
            # We use __dict__ to see if it's defined in the subclass itself
            has_local_execute = "execute" in agent.__class__.__dict__
            
            # Special case for ApplicationAgent which HAS a valid wrapper
            if name == "application_agent": has_local_execute = False

            _valid = is_base and has_handlers and not has_local_execute
            
            if not _valid:
                logger.warning(f"  [!] Agent '{name}' fails O(1) contract: "
                               f"base={is_base}, handlers={has_handlers}, local_exec={has_local_execute}")
                all_valid = False
        return all_valid

    # ──────────────────────────────────────────────────────────────────────────
    #  EventBus subscriptions — observability wiring
    # ──────────────────────────────────────────────────────────────────────────

    def _wire_event_subscriptions(self) -> None:
        bus = self.event_bus

        def _on_safety_blocked(event: dict) -> None:
            data = event.get("data", {})
            logger.warning(
                f"[SafetyBlock] task={data.get('task_id','?')[:8]} "
                f"reason={data.get('reason','?')}"
            )

        def _on_escalation(event: dict) -> None:
            data = event.get("data", {})
            logger.error(
                f"[HumanEscalation] task={data.get('task_id','?')[:8]} -- "
                "All recovery strategies exhausted. Human intervention needed."
            )

        def _on_task_failed(event: dict) -> None:
            data = event.get("data", {})
            logger.warning(
                f"[TaskFailed] task={data.get('task_id','?')[:8]} "
                f"error={data.get('error','?')[:120]}"
            )

        bus.subscribe("safety_check_blocked", _on_safety_blocked)
        bus.subscribe("human_escalation_required", _on_escalation)
        bus.subscribe("task_failed", _on_task_failed)
        logger.info("  EventBus subscriptions wired")

    # ──────────────────────────────────────────────────────────────────────────
    #  Callbacks
    # ──────────────────────────────────────────────────────────────────────────

    def _on_task_submitted(self, task_text: str) -> None:
        if self.brain:
            logger.info(f"Task submitted: {task_text}")
            self.brain.process_request(task_text)

    def _on_game_task_update(self, tasks: List[Dict]) -> None:
        if self.game:
            self.game.update_task_display(tasks)

    def _status_update_loop(self) -> None:
        while self.running:
            try:
                if self.ui and self.brain:
                    self.ui.update_task_list(self.brain.get_all_tasks())
                time.sleep(2)
            except Exception as exc:
                logger.debug(f"Status loop: {exc}")
                time.sleep(5)

    # ──────────────────────────────────────────────────────────────────────────
    #  Lifecycle
    # ──────────────────────────────────────────────────────────────────────────

    def run(self) -> None:
        self.running = True
        logger.info("NovaMind Ecosystem running.")

        if self.event_bus:
            self.event_bus.emit_sync("session_started", {
                "version": __version__,
                "timestamp": datetime.now().isoformat(),
            })

        threading.Thread(
            target=self._status_update_loop, daemon=True
        ).start()

        # Start asyncio bridge thread
        if self.bridge_server:
            import asyncio
            def _run_bridge():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                async def _start_all():
                    if self.task_manager:
                        self.task_manager.start()
                    if self.event_recorder:
                        await self.event_recorder.start()
                    await self.bridge_server.start()
                
                try:
                    loop.run_until_complete(_start_all())
                    loop.run_forever()
                except Exception as e:
                    logger.error(f"Bridge Thread crashed: {e}")
                finally:
                    loop.run_until_complete(self.bridge_server.stop())
                    loop.close()
            
            self._bridge_thread = threading.Thread(target=_run_bridge, daemon=True)
            self._bridge_thread.start()

        if self.ui and not self.headless:
            self.ui.show()
            from PyQt6.QtWidgets import QApplication
            qt = QApplication.instance()
            if qt:
                sys.exit(qt.exec())
        else:
            logger.info("Ecosystem Server active. Waiting for Godot Client connection... Press Ctrl+C to stop.")
            try:
                while self.running:
                    time.sleep(1)
            except KeyboardInterrupt:
                self.stop()

    def stop(self) -> None:
        logger.info("Shutting down ...")
        self.running = False
        if self.event_bus:
            self.event_bus.emit_sync("session_ended", {
                "timestamp": datetime.now().isoformat()
            })
        if self.scheduler:
            self.scheduler.stop()
        if self.bridge_server:
            # We cancel the asyncio loop via thread-safe call if needed, 
            # but daemon thread will kill it cleanly on exit.
            pass
        if self.brain:
            self.brain.stop()
        if self.memory:
            self.memory.end_session()
            self.memory.close()
        logger.info("Done.")

    def run_cli_task(self, task: str) -> None:
        if not self.brain:
            logger.error("Brain not initialised")
            return
        logger.info(f"CLI task: {task}")
        execution = self.brain.process_request(task)
        deadline = time.time() + 300
        while time.time() < deadline:
            s = self.brain.get_task_status(execution.task_id)
            if s and s["status"] not in ("pending", "running", "retrying"):
                break
            if s:
                logger.info(f"  Status: {s['status']} "
                            f"({s['completed_steps']}/{s['total_steps']} steps)")
            time.sleep(2)
        final = self.brain.get_task_status(execution.task_id)
        logger.info(f"\nFinal status: {final['status'] if final else 'unknown'}")
        for res in execution.results:
            logger.info(f"  Step {res.step_number}: {res.status.value}")
            if res.output:
                logger.info(f"    Output: {res.output[:300]}")
            if res.error:
                logger.info(f"    Error:  {res.error[:200]}")

    def get_status(self) -> Dict:
        event_log_size = (
            len(self.event_bus.get_session_log()) if self.event_bus else 0
        )
        return {
            "version":    __version__,
            "uptime":     str(datetime.now() - self.start_time),
            "dependencies": self.deps,
            "agents":     list(self.agents.keys()),
            "components": {
                "brain":              self.brain is not None,
                "vision":             self.vision is not None,
                "memory":             self.memory is not None,
                "security":           self.security is not None,
                "event_bus":          self.event_bus is not None,
                "state_manager":      self.state_manager is not None,
                "verifier_agent":     self.verifier is not None,
                "recovery_agent":     self.recovery_agent is not None,
                "application_agent":  "application_agent" in self.agents,
                "parallel_engine":    True,
            },
            "event_log_size": event_log_size,
        }


# ─────────────────────────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────────────────────────

def create_env_template() -> None:
    env_path = runtime_path(".env")
    template = """# NovaMind API Keys — uncomment the key(s) you have

# GROQ_API_KEY=your_groq_key_here
# TOGETHER_API_KEY=your_together_key_here
# OPENROUTER_API_KEY=your_openrouter_key_here
# XAI_API_KEY=your_xai_key_here
# GEMINI_API_KEY=your_gemini_key_here
# HYPERBOLIC_API_KEY=your_hyperbolic_key_here
# NVIDIA_API_KEY=your_nvidia_key_here
# CEREBRAS_API_KEY=your_cerebras_key_here
"""
    try:
        with open(env_path, "x", encoding="utf-8") as f:
            f.write(template)
        logger.info("Created .env template at %s", env_path)
    except FileExistsError:
        logger.info(".env already exists at %s", env_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="NovaMind — Autonomous Desktop AI Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                                       # Full GUI + game
  python main.py --task "Draw a blue sports car in MS Paint"
  python main.py --task "Search for Python tutorials"
  python main.py --headless --task "List files in Downloads"
  python main.py --no-game                             # GUI without 3D game
  python main.py --status                              # System status
  python main.py --setup                               # Create API key template
""",
    )
    parser.add_argument("--task", "-t",
                        help="Run a single task then exit")
    parser.add_argument("--headless", action="store_true",
                        help="No GUI/game")
    parser.add_argument("--no-game", action="store_true",
                        help="GUI without 3D game")
    parser.add_argument("--status", action="store_true",
                        help="Print system status")
    parser.add_argument("--health", action="store_true",
                        help="Print structured health check and exit")
    parser.add_argument("--setup", action="store_true",
                        help="Create .env template")
    parser.add_argument("--version", "-v", action="version",
                        version=f"NovaMind {__version__}")
    args = parser.parse_args()

    print_banner()

    if args.setup:
        create_env_template()
        return

    if args.health:
        import shutil
        _runtime_root = get_runtime_root()
        _db_path = runtime_path("memory.db")
        _log_path = ensure_runtime_dir("logs")
        _disk = shutil.disk_usage(_runtime_root)
        _api_keys_present = [
            k for k in (
                "GROQ_API_KEY", "TOGETHER_API_KEY", "OPENROUTER_API_KEY",
                "XAI_API_KEY", "GEMINI_API_KEY",
            ) if os.environ.get(k)
        ]
        health = {
            "version":         __version__,
            "status":          "ok",
            "runtime_root":    str(_runtime_root),
            "db_exists":       os.path.isfile(_db_path),
            "log_dir_exists":  os.path.isdir(_log_path),
            "disk_free_gb":    round(_disk.free / 1024**3, 2),
            "api_keys_found":  _api_keys_present,
            "python_version":  sys.version,
        }
        print(json.dumps(health, indent=2))
        return
    deps = check_dependencies()
    logger.info("Dependencies:")
    for name, ok in deps.items():
        logger.info(f"  {'[v]' if ok else '[x]'} {name}")

    app = NovaMindApp(headless=args.headless,
                      no_game=getattr(args, "no_game", False))
    if not app.initialize():
        logger.error("Initialisation failed -- check logs")
        sys.exit(1)

    if args.status:
        print(json.dumps(app.get_status(), indent=2))
        return

    if args.task:
        app.run_cli_task(args.task)
        app.stop()
        return

    try:
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()


if __name__ == "__main__":
    main()
