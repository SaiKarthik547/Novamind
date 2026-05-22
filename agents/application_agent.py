"""
Application Agent — Universal Windows Desktop Automation
Controls ANY Windows application via LLM-planned + vision-verified pyautogui.

Launch strategy (most reliable first):
  1. Windows Search  (Win → type app name → Enter)   ⇐ human-like, works for ANYTHING
  2. Win+R Run dialog (for known exe/protocol names)
  3. subprocess shell  (direct exe, last resort)

Dynamic behaviour:
  - All waits are screen-change-aware, not fixed sleeps
  - Text input uses clipboard for reliability (handles Unicode + special chars)
  - Error recovery: re-reads screen, replans with failure context
"""
from __future__ import annotations

import io
import json
import math
import os
import platform
import re
import subprocess
import threading
import time
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from agents.apps.paint_agent import PaintAgent
from core.foundation.base_agent import BaseAgent
from core.os_utils.perception import PerceptionEngine

logger = logging.getLogger("AppAgent")

# ── Optional imports ─────────────────────────────────────────────────────────
try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE    = 0.03
    PYAUTOGUI_OK = True
except ImportError:
    PYAUTOGUI_OK = False

try:
    import pygetwindow as gw
    PYGETWINDOW_OK = True
except ImportError:
    PYGETWINDOW_OK = False

try:
    from PIL import Image, ImageChops, ImageStat
    PIL_OK = True
except ImportError:
    PIL_OK = False

try:
    import pytesseract
    TESSERACT_OK = True
except ImportError:
    TESSERACT_OK = False

try:
    import easyocr
    EASYOCR_OK = True
except ImportError:
    EASYOCR_OK = False

_easyocr_reader = None   # lazy-initialised on first use

try:
    import pyperclip
    PYPERCLIP_OK = True
except ImportError:
    PYPERCLIP_OK = False

try:
    import numpy as np
    NUMPY_OK = True
except ImportError:
    NUMPY_OK = False

# ── os_executor / uia_executor (real OS-level execution layer) ───────────────
try:
    from core.os_utils.os_executor import (
        OSExecutor, assert_window_focused,
        safe_drag, safe_click, safe_hotkey, safe_type, safe_type_clipboard,
        safe_press, safe_hold, safe_move, safe_scroll,
        release_all_modifiers, ActionVerifier, FocusLostError, DPI_SCALE,
        get_audit_log, _CHAOS_HOOKS,
    )
    from core.os_utils.uia_executor import UIAExecutor
    OS_EXECUTOR_OK = True
except ImportError:
    OS_EXECUTOR_OK = False
    FocusLostError = Exception   # alias so type hints still work


# ── App → exe / URI mapping (fallback only; primary is Windows Search) ───────
APP_EXE_MAP: Dict[str, str] = {
    "paint": "mspaint.exe",       "mspaint": "mspaint.exe",
    "notepad": "notepad.exe",     "wordpad": "wordpad.exe",
    "calculator": "calc.exe",     "calc": "calc.exe",
    "explorer": "explorer.exe",   "file explorer": "explorer.exe",
    "cmd": "cmd.exe",             "command prompt": "cmd.exe",
    "powershell": "powershell.exe",
    "task manager": "taskmgr.exe",
    "regedit": "regedit.exe",
    "control panel": "control.exe",
    "snipping tool": "snippingtool.exe",
    "chrome": "chrome.exe",       "google chrome": "chrome.exe",
    "edge": "msedge.exe",         "microsoft edge": "msedge.exe",
    "firefox": "firefox.exe",
    "word": "winword.exe",        "microsoft word": "winword.exe",
    "excel": "excel.exe",         "microsoft excel": "excel.exe",
    "powerpoint": "powerpnt.exe",
    "outlook": "outlook.exe",
    "teams": "teams.exe",
    "slack": "slack.exe",
    "discord": "discord.exe",
    "zoom": "zoom.exe",
    "vs code": "code.exe",        "vscode": "code.exe",
    "spotify": "spotify.exe",
    "vlc": "vlc.exe",
    "obs": "obs64.exe",           "obs studio": "obs64.exe",
    "steam": "steam.exe",
}

# Window title keywords for each known app
APP_TITLE_HINTS: Dict[str, str] = {
    "paint": "Paint",             "mspaint": "Paint",
    "notepad": "Notepad",         "wordpad": "WordPad",
    "calculator": "Calculator",   "calc": "Calculator",
    "explorer": "Explorer",       "file explorer": "Explorer",
    "cmd": "Command Prompt",      "command prompt": "Command Prompt",
    "powershell": "PowerShell",
    "chrome": "Chrome",           "google chrome": "Chrome",
    "edge": "Edge",               "microsoft edge": "Edge",
    "firefox": "Firefox",
    "word": "Word",               "microsoft word": "Word",
    "excel": "Excel",             "microsoft excel": "Excel",
    "powerpoint": "PowerPoint",
    "outlook": "Outlook",
    "teams": "Teams",
    "slack": "Slack",
    "discord": "Discord",
    "zoom": "Zoom",
    "vs code": "Visual Studio Code",
    "vscode": "Visual Studio Code",
    "visual studio code": "Visual Studio Code",
    "spotify": "Spotify",
    "vlc": "VLC",
    "obs": "OBS",                 "obs studio": "OBS",
    "steam": "Steam",
    "task manager": "Task Manager",
    "snipping tool": "Snipping",
    "regedit": "Registry Editor",
    "control panel": "Control Panel",
}


# ── Agent ────────────────────────────────────────────────────────────────────
class ApplicationAgent(BaseAgent):
    """
    Universal Windows desktop automation agent.
    Every action is real: pyautogui mouse + keyboard, screen capture, OCR.
    No simulations. Decisions adapt to what is actually on screen.
    """

    # How many consecutive step failures before replanning
    REPLAN_THRESHOLD = 2

    def __init__(self):
        super().__init__(name=self.__class__.__name__, role="Agent")
        self._current_color: Tuple[int, int, int] = (0, 0, 0)
        self._lock = threading.Lock()
        self._last_screenshot: Optional[Any] = None   # PIL Image
        self._paint = PaintAgent()
        self._perception = PerceptionEngine()

        self.handlers = {
            "open_application":       self.open_application,
            "close_application":      self.close_application,
            "focus_window":           self.focus_window,
            "wait_for_window":        self.wait_for_window,
            "get_window_list":        self.get_window_list,
            "resize_window":          self.resize_window,
            "move_window":            self.move_window,
            "minimize_window":        self.minimize_window,
            "maximize_window":        self.maximize_window,
            "restore_window":         self.restore_window,
            "click":                  self.click,
            "double_click":           self.double_click,
            "right_click":            self.right_click,
            "middle_click":           self.middle_click,
            "move_mouse":             self.move_mouse,
            "drag":                   self.drag,
            "scroll":                 self.scroll,
            "type_text":              self.type_text,
            "press_key":              self.press_key,
            "hotkey":                 self.hotkey,
            "hold_key":               self.hold_key,
            "do_task_in_app":         self.do_task_in_app,
            "click_element_by_text":  self.click_element_by_text,
            "fill_field":             self.fill_field,
            "select_menu_item":       self.select_menu_item,
            "wait_for_text":          self.wait_for_text,
            "wait_for_element":       self.wait_for_element,
            "verify_text_on_screen":  self.verify_text_on_screen,
            "screenshot":             self.take_screenshot,
            "read_screen":            self.read_screen,
            "get_screen_info":        self.get_screen_info,
            "open_folder":            self.open_folder,
            "open_file_with":         self.open_file_with,
            "paint_task":             lambda params: self._paint.execute("draw_task", params),
        }

        if PYAUTOGUI_OK:
            logger.info("ApplicationAgent ready")
        else:
            logger.warning("pyautogui not installed — desktop automation disabled")

    def _get_active_window_title(self) -> str:
        """Fetch the current foreground window title for focus-safe auditing."""
        try:
            return gw.getActiveWindow().title if PYGETWINDOW_OK else ""
        except:
            return ""

    # ── Public execute dispatcher ────────────────────────────────────────────

    def execute(self, action: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        if not PYAUTOGUI_OK:
            return {"success": False, "error": "pyautogui not installed. pip install pyautogui"}
        
        return super(ApplicationAgent, self).execute(action, parameters)

    # ── APP LAUNCH — Strategy Registry (O(1) dispatch) ───────────────────────

    def open_application(self, app_name: str,
                          wait: float = None,
                          args: List[str] = None,
                          working_dir: str = None) -> Dict:
        """
        Open any application. Tries a priority-ordered strategy chain.
        Each strategy is a callable returning a result dict with 'success' key.
        The chain is driven by next() on a filtered generator — zero if/elif.
        """
        title_hint = self._window_title_hint(app_name)
        max_wait   = wait if wait is not None else 25.0
        exe        = APP_EXE_MAP.get(app_name.lower().strip(), app_name)

        # Strategy registry: (name, callable) — tried in priority order
        # Non-Windows systems skip to shell immediately via filter
        _strategies = [
            ("windows_search", lambda: self._open_via_windows_search(app_name, title_hint, max_wait)),
            ("run_dialog",     lambda: self._open_via_run_dialog(exe, title_hint, max_wait)),
            ("shell",          lambda: self._open_via_shell(app_name, args or [], working_dir, title_hint, max_wait)),
        ]

        _is_windows = platform.system() == "Windows"
        # On non-Windows: skip search and run_dialog, only try shell
        _available = {True: _strategies, False: [_strategies[-1]]}
        strategy_list = _available[_is_windows]

        # Drive chain: first successful result wins (generator + next)
        def _try_strategy(name, fn):
            try:
                r = fn()
                logger.debug(f"[open_app] strategy={name} success={r.get('success')}")
                return r
            except Exception as e:
                logger.warning(f"[open_app] strategy={name} raised: {e}")
                return {"success": False, "error": str(e)}

        results_gen = (_try_strategy(n, f) for n, f in strategy_list)
        success_gen = (r for r in results_gen if r.get("success"))
        return next(success_gen, {"success": False, "error": f"All launch strategies failed for '{app_name}'"})


    def _open_via_windows_search(self, app_name: str,
                                  title_hint: str,
                                  max_wait: float) -> Dict:
        """Press Win, type the app name, wait for search results, press Enter."""
        try:
            # Close any open Start menu first
            safe_hotkey("", "escape")
            time.sleep(0.15)

            # Open Windows Search
            safe_hotkey("", "win")
            self._wait_for_screen_change(timeout=3.0)

            # Type the app name naturally (human-like cadence)
            self._human_type(app_name)
            time.sleep(0.8)   # let search results populate

            # Confirm with Enter
            safe_hotkey("", "enter")
            logger.info(f"Windows Search: typed '{app_name}' + Enter")

            # Wait for app window to appear
            appeared = self._wait_for_any_window(title_hint, max_wait)
            if appeared.get("success", False):
                return {"success": True, "app": app_name,
                        "method": "windows_search", "title": appeared.get("title", "")}
            return {"success": False, "error": f"Window '{title_hint}' did not appear"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _open_via_run_dialog(self, exe: str,
                              title_hint: str,
                              max_wait: float) -> Dict:
        """Win+R → type exe → Enter."""
        try:
            pyautogui.hotkey("win", "r")
            self._wait_for_screen_change(timeout=3.0)
            time.sleep(0.3)
            self._human_type(exe)
            time.sleep(0.2)
            pyautogui.press("enter")
            logger.info(f"Win+R: ran '{exe}'")
            appeared = self._wait_for_any_window(title_hint, max_wait)
            if appeared.get("success", False):
                return {"success": True, "app": exe,
                        "method": "run_dialog", "title": appeared.get("title", "")}
            return {"success": False, "error": f"Window '{title_hint}' not found after Win+R"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _open_via_shell(self, app_name: str, args: List[str],
                         working_dir: str = None,
                         title_hint: str = "",
                         max_wait: float = 20.0) -> Dict:
        """Last-resort: subprocess.Popen."""
        key  = app_name.lower().strip()
        cmd  = APP_EXE_MAP.get(key, app_name)
        # Try `where` to resolve full path on Windows
        if platform.system() == "Windows" and not os.path.isabs(cmd):
            try:
                found = subprocess.check_output(
                    f"where {cmd}", shell=True, text=True, stderr=subprocess.DEVNULL,
                    timeout=15
                ).strip().splitlines()
                if found:
                    cmd = found[0]
            except Exception:
                pass
        try:
            parts = [cmd] + args
            cmd_str = " ".join(f'"{p}"' if " " in p else p for p in parts)
            proc = subprocess.Popen(
                cmd_str,
                shell=True,
                cwd=working_dir or os.path.expanduser("~"),
            )
            logger.info(f"Shell launch: '{cmd_str}' PID={proc.pid}")
            if title_hint:
                appeared = self._wait_for_any_window(title_hint, max_wait)
                if appeared.get("success", False):
                    return {"success": True, "app": cmd, "pid": proc.pid,
                            "method": "shell", "title": appeared.get("title", "")}
            # No title hint — just sleep and assume it worked
            time.sleep(min(max_wait, 4.0))
            return {"success": True, "app": cmd, "pid": proc.pid, "method": "shell"}
        except FileNotFoundError:
            return {"success": False, "error": f"Application not found: {app_name}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── WINDOW MANAGEMENT ────────────────────────────────────────────────────

    def close_application(self, title_contains: str = None,
                           process_name: str = None) -> Dict:
        if process_name and platform.system() == "Windows":
            r = subprocess.run(
                f"taskkill /F /IM {process_name}",
                shell=True, capture_output=True, text=True, timeout=15
            )
            return {"success": r.returncode == 0, "output": r.stdout}
        if title_contains and PYGETWINDOW_OK:
            wins = [w for w in gw.getAllWindows()
                    if title_contains.lower() in w.title.lower()]
            for w in wins:
                try:
                    w.close()
                except Exception:
                    pass
            return {"success": bool(wins), "closed": len(wins)}
        return {"success": False, "error": "Provide title_contains or process_name"}

    def focus_window(self, title_contains: str, timeout: float = 10.0) -> Dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if PYGETWINDOW_OK:
                wins = [w for w in gw.getAllWindows()
                        if title_contains.lower() in w.title.lower() and w.visible]
                if wins:
                    w = wins[0]
                    try:
                        w.activate()
                        self._micro_sleep(0.3, 0.5)
                        w.maximize()
                        self._micro_sleep(0.2, 0.4)
                        return {"success": True, "title": w.title,
                                "left": w.left, "top": w.top,
                                "width": w.width, "height": w.height}
                    except Exception as e:
                        logger.debug(f"activate: {e}")
            time.sleep(0.4)
        return {"success": False, "error": f"Window not found: '{title_contains}'"}

    def wait_for_window(self, title_contains: str, timeout: float = 25.0) -> Dict:
        return self._wait_for_any_window(title_contains, timeout)

    def get_window_list(self) -> Dict:
        if not PYGETWINDOW_OK:
            return {"success": False, "error": "pygetwindow not installed"}
        wins = [{"title": w.title, "visible": w.visible,
                 "left": w.left, "top": w.top,
                 "width": w.width, "height": w.height}
                for w in gw.getAllWindows() if w.title.strip()]
        return {"success": True, "count": len(wins), "windows": wins}

    def resize_window(self, title_contains: str, width: int, height: int) -> Dict:
        if not PYGETWINDOW_OK:
            return {"success": False, "error": "pygetwindow not installed"}
        wins = [w for w in gw.getAllWindows()
                if title_contains.lower() in w.title.lower()]
        if not wins:
            return {"success": False, "error": f"Window not found: {title_contains}"}
        wins[0].resizeTo(width, height)
        return {"success": True, "title": wins[0].title, "width": width, "height": height}

    def move_window(self, title_contains: str, x: int, y: int) -> Dict:
        if not PYGETWINDOW_OK:
            return {"success": False, "error": "pygetwindow not installed"}
        wins = [w for w in gw.getAllWindows()
                if title_contains.lower() in w.title.lower()]
        if not wins:
            return {"success": False, "error": "Window not found"}
        wins[0].moveTo(x, y)
        return {"success": True, "x": x, "y": y}

    def minimize_window(self, title_contains: str) -> Dict:
        if not PYGETWINDOW_OK:
            return {"success": False, "error": "pygetwindow not installed"}
        wins = [w for w in gw.getAllWindows()
                if title_contains.lower() in w.title.lower()]
        if wins:
            wins[0].minimize()
            return {"success": True}
        return {"success": False, "error": "Window not found"}

    def maximize_window(self, title_contains: str) -> Dict:
        if not PYGETWINDOW_OK:
            return {"success": False, "error": "pygetwindow not installed"}
        wins = [w for w in gw.getAllWindows()
                if title_contains.lower() in w.title.lower()]
        if wins:
            wins[0].maximize()
            return {"success": True}
        return {"success": False, "error": "Window not found"}

    def restore_window(self, title_contains: str) -> Dict:
        if not PYGETWINDOW_OK:
            return {"success": False, "error": "pygetwindow not installed"}
        wins = [w for w in gw.getAllWindows()
                if title_contains.lower() in w.title.lower()]
        if wins:
            wins[0].restore()
            return {"success": True}
        return {"success": False, "error": "Window not found"}

    # ── MOUSE ────────────────────────────────────────────────────────────────

    def click(self, x: int = None, y: int = None,
               button: str = "left",
               image: str = None,
               confidence: float = 0.85,
               clicks: int = 1,
               interval: float = 0.0) -> Dict:
        if image and PIL_OK:
            try:
                loc = pyautogui.locateCenterOnScreen(image, confidence=confidence)
                if loc is None:
                    return {"success": False, "error": f"Image not found: {image}"}
                x, y = int(loc.x), int(loc.y)
            except Exception as e:
                return {"success": False, "error": f"Image locate failed: {e}"}
        if x is None or y is None:
            return {"success": False, "error": "Provide x, y or image"}
        
        target_title = self._get_active_window_title()
        safe_click(target_title, x, y, button=button, clicks=clicks, interval=interval)
        return {"success": True, "x": x, "y": y, "button": button, "clicks": clicks}

    def double_click(self, x: int, y: int) -> Dict:
        target_title = self._get_active_window_title()
        safe_click(target_title, x, y, clicks=2)
        return {"success": True, "x": x, "y": y}

    def right_click(self, x: int, y: int) -> Dict:
        target_title = self._get_active_window_title()
        safe_click(target_title, x, y, button="right")
        return {"success": True, "x": x, "y": y}

    def middle_click(self, x: int, y: int) -> Dict:
        target_title = self._get_active_window_title()
        safe_click(target_title, x, y, button="middle")
        return {"success": True, "x": x, "y": y}

    def move_mouse(self, x: int, y: int, duration: float = 0.15) -> Dict:
        target_title = self._get_active_window_title()
        safe_move(target_title, x, y, duration=duration)
        return {"success": True, "x": x, "y": y}

    def drag(self, from_x: int, from_y: int,
              to_x: int, to_y: int,
              duration: float = 0.4,
              button: str = "left") -> Dict:
        target_title = self._get_active_window_title()
        safe_drag(target_title, from_x, from_y, to_x, to_y, button=button, duration=duration)
        return {"success": True, "from": (from_x, from_y), "to": (to_x, to_y)}

    def scroll(self, x: int, y: int,
                clicks: int = 5, direction: str = "down") -> Dict:
        target_title = self._get_active_window_title()
        safe_scroll(target_title, x, y, clicks=clicks, direction=direction)
        return {"success": True, "direction": direction, "clicks": clicks}

    # ── KEYBOARD ─────────────────────────────────────────────────────────────

    def type_text(self, text: str,
                   interval: float = None,
                   clear_first: bool = False) -> Dict:
        """
        Type text reliably.
        - Short pure-ASCII with no special chars → safe_type (direct keys)
        - Everything else → clipboard paste (handles Unicode, symbols, long text)
        """
        if clear_first:
            target_title = self._get_active_window_title()
            safe_hotkey(target_title, "ctrl", "a")
            time.sleep(0.1)
            safe_hotkey(target_title, "delete")
        self._smart_type(text, interval=interval)
        return {"success": True, "text": text, "length": len(text)}

    def press_key(self, key: str, times: int = 1,
                   interval: float = 0.05) -> Dict:
        target_title = self._get_active_window_title()
        safe_press(target_title, key, times=times, interval=interval)
        return {"success": True, "key": key, "times": times}

    def hotkey(self, *keys) -> Dict:
        pyautogui.hotkey(*keys)
        return {"success": True, "keys": list(keys)}

    def hold_key(self, key: str, duration: float = 0.5) -> Dict:
        target_title = self._get_active_window_title()
        safe_hold(target_title, key, duration=duration)
        return {"success": True, "key": key, "duration": duration}

    # ── HIGH-LEVEL: do_task_in_app ───────────────────────────────────────────

    def do_task_in_app(self, app_name: str,
                        task_description: str,
                        max_steps: int = 15) -> Dict:
        """
        Open app if not running, then execute any task inside it via a
        screen-reading + LLM-planning loop.
        """
        steps_done:  List[Dict] = []
        errors:      List[str]  = []
        consec_fail: int        = 0
        replan_ctx:  str        = ""

        found = self._find_window(app_name)
        if not found:
            r = self.open_application(app_name)
            if not r.get("success", False):
                return {"success": False,
                        "error": f"Could not open '{app_name}': {r.get('error', 'unknown error')}",
                        "steps": steps_done}
        else:
            title_hint = self._window_title_hint(app_name)
            self.focus_window(title_hint, timeout=5.0)

        self._wait_for_screen_stable(timeout=4.0)

        MIN_LLM_GAP = 1.2
        _last_llm   = 0.0

        for step_idx in range(max_steps):
            screen_text  = self._read_screen_ocr()
            active_title = self._get_active_title()

            gap = time.time() - _last_llm
            if gap < MIN_LLM_GAP:
                time.sleep(MIN_LLM_GAP - gap)

            action_plan = self._llm_plan_next_action(
                app_name       = app_name,
                task           = task_description,
                screen_text    = screen_text,
                active_window  = active_title,
                steps_done     = steps_done,
                replan_context = replan_ctx,
            )
            _last_llm = time.time()
            replan_ctx = ""

            if action_plan.get("task_complete"):
                break

            if action_plan.get("need_user_input"):
                return {"success": False, "error": f"User input required: {action_plan.get('message', '')}", "steps": steps_done}

            pre_shot = self._grab_screenshot()
            act_result = self._execute_planned_action(action_plan)
            steps_done.append({"step": step_idx + 1, "plan": action_plan, "result": act_result})

            if act_result.get("success"):
                consec_fail = 0
                self._wait_for_screen_change_from(pre_shot, timeout=5.0)
            else:
                err = act_result.get("error", "unknown error")
                errors.append(err)
                consec_fail += 1
                if consec_fail >= self.REPLAN_THRESHOLD:
                    replan_ctx = f"Last {consec_fail} steps failed. approach something fundamentally different."
                    consec_fail = 0
                    errors.clear()
                    try:
                        pyautogui.press("escape")
                        time.sleep(0.3)
                    except Exception: pass
                time.sleep(0.5)

        total_ok   = sum(1 for s in steps_done if s["result"].get("success"))
        total_fail = len(steps_done) - total_ok
        success    = total_ok > 0 and total_fail <= total_ok

        return {
            "success":     success,
            "app":         app_name,
            "task":        task_description,
            "steps_taken": len(steps_done),
            "steps_ok":    total_ok,
            "steps_fail":  total_fail,
            "steps":       steps_done,
        }

    def _llm_plan_next_action(self, app_name: str, task: str,
                                screen_text: str, active_window: str,
                                steps_done: List[Dict],
                                replan_context: str = "") -> Dict:
        """Ask LLM for the single best next action given current screen state."""
        try:
            from core.orchestration.llm_router import get_router
            router = get_router()
            sw, sh = pyautogui.size()
            recent = steps_done[-6:]
            steps_summary = "\n".join(f"  {i+1}. {s['plan'].get('action','?')} {'✓' if s['result'].get('success') else '✗'} {s['plan'].get('reason','')}" for i, s in enumerate(recent))
            replan_note = f"\n⚠ REPLAN NEEDED: {replan_context}" if replan_context else ""

            prompt = f"""You are controlling a Windows desktop via pyautogui.
App: {app_name} | Active window: {active_window} | Resolution: {sw}x{sh}
GOAL: {task} {replan_note}
Screen OCR: {screen_text[:2000]}
Recent actions: {steps_summary or '(none)'}

Choose next action (JSON):
{{
  "task_complete": false,
  "need_user_input": false,
  "message": "",
  "action": "click|double_click|right_click|type|hotkey|press|drag|scroll|wait",
  "x": 0, "y": 0, "text": "", "key": "", "keys": [],
  "from_x": 0, "from_y": 0, "to_x": 0, "to_y": 0,
  "clicks": 1, "direction": "down", "duration": 0.4,
  "reason": "reason"
}}
"""
            response = router.quick_request(prompt, task_type="general")
            m = re.search(r'\{.*\}', response, re.DOTALL)
            if m:
                plan = json.loads(m.group())
                for k in ["x","y","from_x","from_y","to_x","to_y"]:
                    if k in plan: plan[k] = max(0, min(sw-1, int(plan[k])))
                return plan
        except Exception as e:
            logger.warning(f"LLM plan error: {e}")
        return {"action": "wait", "duration": 1.5, "reason": "LLM error fallback"}

    # ── Per-action handlers ──────────────────────────────────────────────────

    def _action_click(self, plan: Dict) -> Dict:
        x, y = int(plan.get("x", 0)), int(plan.get("y", 0))
        pyautogui.click(x, y, button=plan.get("button", "left"))
        return {"success": True, "action": "click", "x": x, "y": y}

    def _action_double_click(self, plan: Dict) -> Dict:
        x, y = int(plan.get("x", 0)), int(plan.get("y", 0))
        pyautogui.doubleClick(x, y)
        return {"success": True, "action": "double_click", "x": x, "y": y}

    def _action_right_click(self, plan: Dict) -> Dict:
        x, y = int(plan.get("x", 0)), int(plan.get("y", 0))
        pyautogui.rightClick(x, y)
        return {"success": True, "action": "right_click", "x": x, "y": y}

    def _action_type(self, plan: Dict) -> Dict:
        txt = str(plan.get("text", ""))
        self._smart_type(txt)
        return {"success": True, "action": "type", "text": txt}

    def _action_hotkey(self, plan: Dict) -> Dict:
        keys = plan.get("keys", [])
        keys and pyautogui.hotkey(*keys)
        return {"success": True, "action": "hotkey", "keys": keys}

    def _action_press(self, plan: Dict) -> Dict:
        key = plan.get("key", "enter")
        pyautogui.press(key)
        return {"success": True, "action": "press", "key": key}

    def _action_drag(self, plan: Dict) -> Dict:
        fx, fy = int(plan.get("from_x", 0)), int(plan.get("from_y", 0))
        tx, ty = int(plan.get("to_x",   0)), int(plan.get("to_y",   0))
        dur    = float(plan.get("duration", 0.4))
        pyautogui.moveTo(fx, fy, duration=0.1)
        pyautogui.mouseDown()
        pyautogui.moveTo(tx, ty, duration=dur)
        pyautogui.mouseUp()
        return {"success": True, "action": "drag", "from": (fx, fy), "to": (tx, ty)}

    def _action_scroll(self, plan: Dict) -> Dict:
        x, y = int(plan.get("x", 0)), int(plan.get("y", 0))
        c, d = int(plan.get("clicks", 3)), plan.get("direction", "down")
        sign = 1 - 2 * (d == "down")
        pyautogui.scroll(sign * c, x=x, y=y)
        return {"success": True, "action": "scroll"}

    def _action_wait(self, plan: Dict) -> Dict:
        dur = min(float(plan.get("duration", 1.5)), 10.0)
        self._wait_for_screen_stable(timeout=dur)
        return {"success": True, "action": "wait", "duration": dur}

    def _execute_planned_action(self, plan: Dict) -> Dict:
        action = plan.get("action", "wait")
        _DISPATCH = {
            "click":        self._action_click,
            "double_click": self._action_double_click,
            "right_click":  self._action_right_click,
            "type":         self._action_type,
            "hotkey":       self._action_hotkey,
            "press":        self._action_press,
            "drag":         self._action_drag,
            "scroll":       self._action_scroll,
            "wait":         self._action_wait,
        }
        handler = _DISPATCH.get(action, lambda p: {"success": False, "error": f"Unknown action: {action}"})
        try:
            return handler(plan)
        except Exception as e:
            try: pyautogui.mouseUp()
            except: pass
            return {"success": False, "error": str(e), "action": action}

    # ── SMART ELEMENT ACTIONS ────────────────────────────────────────────────

    def click_element_by_text(self, text: str,
                               partial: bool = True,
                               timeout: float = 6.0) -> Dict:
        if not TESSERACT_OK and not EASYOCR_OK: return {"success": False, "error": "No OCR"}
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                img  = pyautogui.screenshot()
                data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
                tl = text.lower()
                for i, word in enumerate(data["text"]):
                    if data["conf"][i] < 35: continue
                    wl = word.lower()
                    if (partial and tl in wl) or (not partial and tl == wl):
                        cx = data["left"][i] + data["width"][i] // 2
                        cy = data["top"][i]  + data["height"][i] // 2
                        safe_click(self._get_active_window_title(), cx, cy)
                        return {"success": True, "text": word, "x": cx, "y": cy}
            except Exception as e: return {"success": False, "error": str(e)}
            time.sleep(0.3)
        return {"success": False, "error": f"Text not found: '{text}'"}

    def fill_field(self, field_text: str, value: str,
                    clear_first: bool = True) -> Dict:
        r = self.click_element_by_text(field_text)
        if not r.get("success"): return r
        time.sleep(0.2)
        self.type_text(value, clear_first=clear_first)
        return {"success": True, "field": field_text, "value": value}

    def select_menu_item(self, menu: str, item: str,
                          submenu: str = None) -> Dict:
        r = self.click_element_by_text(menu)
        if not r.get("success"): return r
        self._wait_for_screen_change(timeout=2.0)
        if submenu:
            r2 = self.click_element_by_text(submenu, timeout=3.0)
            if not r2.get("success"): return r2
            self._wait_for_screen_change(timeout=2.0)
        r3 = self.click_element_by_text(item, timeout=3.0)
        if not r3.get("success"):
            safe_hotkey(self._get_active_window_title(), "escape")
            return r3
        return {"success": True, "menu": menu, "item": item}

    def wait_for_text(self, text: str, timeout: float = 20.0,
                       check_interval: float = 0.5) -> Dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            screen = self._read_screen_ocr()
            if text.lower() in screen.lower(): return {"success": True, "text": text}
            time.sleep(check_interval)
        return {"success": False, "error": "Timeout"}

    def wait_for_element(self, image_path: str,
                          timeout: float = 15.0,
                          confidence: float = 0.8) -> Dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                loc = pyautogui.locateCenterOnScreen(image_path, confidence=confidence)
                if loc: return {"success": True, "x": loc.x, "y": loc.y}
            except: pass
            time.sleep(0.5)
        return {"success": False, "error": "Not found"}

    def verify_text_on_screen(self, text: str) -> Dict:
        screen = self._read_screen_ocr()
        return {"success": True, "found": text.lower() in screen.lower(), "text": text}

    # ── SCREENSHOT / SCREEN ──────────────────────────────────────────────────

    def take_screenshot(self, path: str = None, region: tuple = None) -> Dict:
        if path is None:
            ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.expanduser(f"~/.novamind/screenshots/app_{ts}.png")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        img = pyautogui.screenshot(region=region)
        img.save(path)
        return {"success": True, "path": path}

    def read_screen(self) -> Dict:
        text = self._read_screen_ocr()
        return {"success": True, "text": text}

    def get_screen_info(self) -> Dict:
        w, h   = pyautogui.size()
        mx, my = pyautogui.position()
        return {"success": True, "width": w, "height": h, "mouse_x": mx, "mouse_y": my}

    # ── FILE SYSTEM ──────────────────────────────────────────────────────────

    def open_folder(self, path: str) -> Dict:
        path = os.path.expanduser(path)
        if not os.path.isdir(path): return {"success": False, "error": "Not dir"}
        subprocess.Popen(f'explorer "{path}"', shell=True)
        self._wait_for_any_window("Explorer", timeout=8.0)
        return {"success": True, "path": path}

    def open_file_with(self, file_path: str, app: str = None) -> Dict:
        file_path = os.path.expanduser(file_path)
        if not os.path.isfile(file_path): return {"success": False, "error": "Not file"}
        if app: subprocess.Popen(f'"{app}" "{file_path}"', shell=True)
        else: os.startfile(file_path)
        self._wait_for_screen_change(timeout=4.0)
        return {"success": True, "file": file_path}

    # ── INTERNAL HELPERS ─────────────────────────────────────────────────────

    def _find_window(self, app_name: str):
        hint = self._window_title_hint(app_name)
        wins = [w for w in gw.getAllWindows() if hint.lower() in w.title.lower() and w.visible] if PYGETWINDOW_OK else []
        return wins[0] if wins else None

    def _window_title_hint(self, app_name: str) -> str:
        return APP_TITLE_HINTS.get(app_name.lower().strip(), app_name)

    def _wait_for_any_window(self, title_hint: str, timeout: float = 20.0) -> Dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if PYGETWINDOW_OK:
                wins = [w for w in gw.getAllWindows() if title_hint.lower() in w.title.lower() and w.visible]
                if wins:
                    try: wins[0].activate()
                    except: pass
                    return {"success": True, "title": wins[0].title}
            time.sleep(0.35)
        return {"success": False, "error": "Timeout"}

    def _grab_screenshot(self) -> Optional[Any]:
        try: return pyautogui.screenshot()
        except: return None

    def _image_diff_pct(self, img_a, img_b) -> float:
        if not PIL_OK or not NUMPY_OK or img_a is None or img_b is None: return 100.0
        try:
            a, b = np.array(img_a.convert("L")), np.array(img_b.convert("L"))
            if a.shape != b.shape: return 100.0
            return float((np.abs(a - b) > 10).sum() / a.size * 100.0)
        except: return 100.0

    def _wait_for_screen_change(self, timeout: float = 5.0, threshold_pct: float = 0.3) -> bool:
        baseline = self._grab_screenshot()
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.15)
            if self._image_diff_pct(baseline, self._grab_screenshot()) >= threshold_pct: return True
        return False

    def _wait_for_screen_change_from(self, baseline, timeout: float = 5.0, threshold_pct: float = 0.3) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.15)
            if self._image_diff_pct(baseline, self._grab_screenshot()) >= threshold_pct: return True
        return False

    def _wait_for_screen_stable(self, timeout: float = 4.0, stable_for: float = 0.4, threshold_pct: float = 0.15) -> bool:
        stable_since, prev, deadline = None, self._grab_screenshot(), time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.15)
            curr = self._grab_screenshot()
            if self._image_diff_pct(prev, curr) < threshold_pct:
                if stable_since is None: stable_since = time.time()
                elif time.time() - stable_since >= stable_for: return True
            else: stable_since = None
            prev = curr
        return False

    def _smart_type(self, text: str, interval: float = None):
        if not text: return
        is_ascii = all(ord(c) < 128 for c in text)
        if is_ascii and len(text) <= 40:
            safe_type(text, self._get_active_window_title(), interval=interval or 0.03)
        else:
            orig = pyperclip.paste()
            pyperclip.copy(text)
            time.sleep(0.08)
            safe_hotkey(self._get_active_window_title(), "ctrl", "v")
            time.sleep(0.12)
            pyperclip.copy(orig)

    def _human_type(self, text: str):
        import random
        for ch in text:
            try:
                safe_type(ch, self._get_active_window_title(), interval=0.0)
                time.sleep(random.uniform(0.04, 0.12))
            except: pass

    def _read_screen_ocr(self) -> str:
        if TESSERACT_OK:
            try: return pytesseract.image_to_string(pyautogui.screenshot())
            except: pass
        return ""

    def _get_active_title(self) -> str:
        if PYGETWINDOW_OK:
            try: return gw.getActiveWindow().title
            except: pass
        return ""

    def _micro_sleep(self, lo: float, hi: float):
        import random
        time.sleep(random.uniform(lo, hi))

    def _log(self, action: str, params: Dict, success: bool, error: str = None):
        self._action_log.append({"ts": datetime.now().isoformat(), "action": action, "params": {k:v for k,v in params.items() if k!="image_data"}, "success": success, "error": error})
        self._action_log[:] = self._action_log[-2000:]

    def get_log(self) -> List[Dict]:
        return self._action_log[-100:]
