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

# ── Logging ──────────────────────────────────────────────────────────────────
log_file = runtime_path("logs", f"novamind_{datetime.now().strftime('%Y%m%d')}.log")


def _build_log_handlers() -> List[logging.Handler]:
    handlers: List[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    try:
        handlers.insert(
            0,
            logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            ),
        )
    except OSError as exc:
        sys.stderr.write(f"[NovaMind] file logging disabled: {exc}\n")
    return handlers


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-20s | %(levelname)-7s | %(message)s",
    handlers=_build_log_handlers(),
)
logger = logging.getLogger("NovaMind")

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
        "ursina":                lambda: __import__("ursina"),
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

        # Optional
        self.game = None
        self.ui   = None

    def initialize(self) -> bool:
        logger.info("Initialising NovaMind v3 ...")
        load_env_keys()

        if not self.deps.get("requests"):
            logger.error("requests is required: pip install requests")
            return False

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
            logger.info("  EventBus ready")
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

        # Game (optional)
        def _init_game():
            logger.info("  Nova Mindscape (game)")
            try:
                from game.nova_mindscape_launcher import GameProcessManager
                from game.nova_mindscape import GameConfig
                _cfg = GameConfig()
                self.game = GameProcessManager(
                    config_dict=_cfg.__dict__ if hasattr(_cfg, "__dict__") else {},
                    task_callback=self._on_game_task_update,
                )
                logger.info("  Game ready (process manager)")
            except Exception as exc:
                logger.warning(f"  Game init failed: {exc}")

        _check_game = {True: _init_game}
        _check_game.get(bool(not self.headless and not self.no_game and self.deps.get("ursina")), lambda: None)()

        # Scheduler
        logger.info("-> Task Scheduler")
        try:
            from core.scheduler import TaskScheduler
            self.scheduler = TaskScheduler(brain=self.brain, memory=self.memory)
            self.scheduler.start()
            if self.game:
                game_ref = self.game
                self.scheduler.register_callback(
                    lambda tasks, g=game_ref: g.update_tasks(tasks)
                )
            logger.info("  Scheduler ready")
        except Exception as exc:
            logger.warning(f"  Scheduler init failed: {exc}")

        # UI (optional)
        def _init_ui():
            logger.info("-> Task UI")
            try:
                from ui.task_window import TaskWindow
                from PyQt6.QtWidgets import QApplication
                self._qt_app = QApplication.instance() or QApplication(sys.argv)
                self.ui = TaskWindow(brain=self.brain, game=self.game)
                self.ui.task_submitted.connect(self._on_task_submitted)
                logger.info("  UI ready")
            except Exception as exc:
                logger.warning(f"  UI init failed: {exc}")

        def _ui_disabled_msg():
            logger.warning("  PyQt6 not installed -- UI disabled")

        _ui_logic = {
            (True, True):  _init_ui,
            (True, False): _ui_disabled_msg,
        }
        _ui_logic.get((not self.headless, bool(self.deps.get("pyqt6"))), lambda: None)()

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
                if self.game and self.brain:
                    self.game.update_task_display(self.brain.get_all_tasks())
                time.sleep(2)
            except Exception as exc:
                logger.debug(f"Status loop: {exc}")
                time.sleep(5)

    # ──────────────────────────────────────────────────────────────────────────
    #  Lifecycle
    # ──────────────────────────────────────────────────────────────────────────

    def run(self) -> None:
        self.running = True
        logger.info("NovaMind running.")

        if self.event_bus:
            self.event_bus.emit_sync("session_started", {
                "version": __version__,
                "timestamp": datetime.now().isoformat(),
            })

        threading.Thread(
            target=self._status_update_loop, daemon=True
        ).start()

        if self.game and not self.headless:
            self.game.start()

        if self.ui and not self.headless:
            self.ui.show()
            from PyQt6.QtWidgets import QApplication
            qt = QApplication.instance()
            if qt:
                sys.exit(qt.exec())

        else:
            logger.info("Headless mode active. Press Ctrl+C to stop.")
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
        if self.brain:
            self.brain.stop()
        if self.memory:
            self.memory.end_session()
            self.memory.close()
        if self.game:
            self.game.stop()
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
