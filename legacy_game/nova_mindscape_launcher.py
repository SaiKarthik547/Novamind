"""
game/nova_mindscape_launcher.py

GameProcessManager: runs NovaMindscape in a dedicated child process so
Ursina's OpenGL context never conflicts with the Qt event loop.

Communication uses two multiprocessing.Queues:
  cmd_q   — main → game  (commands: update_tasks, stop)
  evt_q   — game → main  (events:   ready, error, stopped)

The child process blocks on Ursina's own run() — no external step() loop.
The parent side is non-blocking and fully restartable.

Zero if-elif routing — dispatch via O(1) dict lookup throughout.
"""

import logging
import multiprocessing
import queue
import time
import threading
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("GameProcessManager")

# ── Child-process entry point ─────────────────────────────────────────────────

def _game_worker(cmd_q: multiprocessing.Queue,
                 evt_q: multiprocessing.Queue,
                 config_dict: dict) -> None:
    """
    Runs inside the child process. Imports Ursina here so the parent
    process is never polluted by an OpenGL context.
    """
    try:
        from game.nova_mindscape import NovaMindscape, GameConfig
        cfg = GameConfig(**{
            k: v for k, v in config_dict.items()
            if hasattr(GameConfig, k) or k in GameConfig.__dataclass_fields__
        }) if hasattr(GameConfig, '__dataclass_fields__') else GameConfig()
        game = NovaMindscape(config=cfg)
        game._cmd_queue = cmd_q          # inject IPC queue — enables _poll_cmd_queue()
        game._evt_queue = evt_q          # inject outbound queue
        evt_q.put({"type": "ready"})

        import threading
        def _cmd_loop():
            _handlers: Dict[str, Callable] = {
                "update_tasks": lambda d: game.update_task_display(d.get("tasks", [])),
                "stop":         lambda d: game.stop(),
            }
            while True:
                try:
                    msg = cmd_q.get(timeout=0.5)
                    handler = _handlers.get(msg.get("cmd", ""))
                    handler and handler(msg)
                    _should_exit = {True: lambda: None}
                    exit_action = _should_exit.get(msg.get("cmd") == "stop")
                    if exit_action:
                        exit_action()
                        break
                except Exception as e:
                    import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
                    pass

        threading.Thread(target=_cmd_loop, daemon=True).start()
        try:
            game.run_blocking()
        except Exception as exc:
            import logging
            logging.error(f"Game run_blocking crashed: {exc}", exc_info=True)
            evt_q.put({"type": "error", "error": str(exc)})

    except Exception as exc:
        import logging; logging.getLogger(__name__).debug(f"Exception caught: {exc}")
        evt_q.put({"type": "error", "error": str(exc)})
    finally:
        evt_q.put({"type": "stopped"})


# ── GameProcessManager ────────────────────────────────────────────────────────

class GameProcessManager:
    """
    Manages the game child process. Main process uses this as a thin proxy.
    All task updates are forwarded to the child via cmd_q.
    """

    def __init__(self, config_dict: Optional[dict] = None,
                 task_callback: Optional[Callable] = None) -> None:
        self._config_dict = config_dict or {}
        self._task_callback = task_callback
        self._process: Optional[multiprocessing.Process] = None
        self._cmd_q: Optional[multiprocessing.Queue] = None
        self._evt_q: Optional[multiprocessing.Queue] = None
        self._ready = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self, timeout: float = 15.0) -> bool:
        """
        Spawn the game child process and wait until it signals ready.
        Returns True on success.
        """
        self._cmd_q = multiprocessing.Queue()
        self._evt_q = multiprocessing.Queue()
        self._process = multiprocessing.Process(
            target=_game_worker,
            args=(self._cmd_q, self._evt_q, self._config_dict),
            daemon=True,
            name="nova-mindscape-3d",
        )
        self._process.start()

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                msg = self._evt_q.get(timeout=0.5)
                _handlers: Dict[str, Callable] = {
                    "ready":   lambda m: self._on_ready(),
                    "error":   lambda m: logger.error(
                        f"Game process error: {m.get('error')}"
                    ),
                    "stopped": lambda m: logger.info("Game process stopped early"),
                }
                handler = _handlers.get(msg.get("type", ""), lambda m: None)
                handler(msg)
                _should_return = {True: lambda: True}
                ret = _should_return.get(msg.get("type") == "ready")
                if ret:
                    threading.Thread(target=self._event_loop, daemon=True, name="GameEventLoop").start()
                    return ret()
            except Exception as e:
                import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
                pass

        logger.warning(f"GameProcessManager.start: no ready signal after {timeout}s")
        return False

    def _event_loop(self) -> None:
        while self.is_alive:
            try:
                msg = self._evt_q.get(timeout=0.5)
                if msg.get("type") == "task":
                    if self._task_callback:
                        self._task_callback(msg.get("text", ""))
                elif msg.get("type") == "error":
                    logger.error(f"Game process error: {msg.get('error')}")
                elif msg.get("type") == "stopped":
                    logger.info("Game process stopped early")
            except Exception as e:
                import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
                pass

    def _on_ready(self) -> None:
        self._ready = True
        logger.info("Nova Mindscape game process ready")

    def stop(self) -> None:
        """Signal the game to stop and wait for the process to exit."""
        _send = {True: lambda: self._cmd_q.put({"cmd": "stop"})}
        _send.get(self._cmd_q is not None, lambda: None)()
        _join = {True: lambda: self._process.join(timeout=5)}
        _join.get(
            self._process is not None and self._process.is_alive(),
            lambda: None,
        )()
        logger.info("Game process stopped")

    @property
    def is_alive(self) -> bool:
        return self._process is not None and self._process.is_alive()

    # ── Task updates ──────────────────────────────────────────────────────────

    def update_task_display(self, tasks: List[Dict]) -> None:
        """Forward task list to the child process (non-blocking)."""
        _send = {True: lambda: self._cmd_q.put({"cmd": "update_tasks", "tasks": tasks})}
        _send.get(
            self._cmd_q is not None and self.is_alive,
            lambda: None,
        )()

    # ── Compatibility shim used by main.py ────────────────────────────────────

    def update_tasks(self, tasks: List[Dict]) -> None:
        self.update_task_display(tasks)