# NovaMind Audit — UI, Vision, and Workers

**Audit date:** 2026-10-06  
**Scope:** `ui/`, `vision/`, `workers/`.  
**Method:** files read directly; where large, the audit characterizes the real parts and flags unverified parts.

---

## 1. `ui/` — PyQt6 task window (currently disabled)

### 1.1 `ui/__init__.py`

Empty.

### 1.2 `ui/task_window.py`

- A PyQt6-based task window. I read enough to know it is a real GUI module, not a stub file, but the full internal logic is large and was not fully covered.
- `main.py` explicitly disables it:

```python
def _init_ui():
    logger.info("-> Task UI")
    try:
        self.ui = None
        self._qt_app = None
        logger.info("  UI disabled (using Game UI only)")
    except Exception as exc:
        logger.warning(f"  UI init failed: {exc}")
```

and the dispatch logic:

```python
_ui_logic = {
    (True, True):  _init_ui,
    (True, False): _ui_disabled_msg,
}
_ui_logic.get((not self.headless and not getattr(self, "game", None), bool(self.deps.get("pyqt6"))), lambda: None)()
```

So the desktop UI is intentionally turned off in the current boot path in favor of a "Game UI". That matches the repo having two candidate front ends (PyQt6 task window vs Godot/Ursina game) and choosing the game path for now.

---

## 2. `vision/` — real vision wrappers

### 2.1 `vision/__init__.py`

Empty.

### 2.2 `vision/vision_system.py`

- Real vision layer using optional `pyautogui`, `PIL`, `pytesseract`, `cv2`/`numpy`, `easyocr`.
- `VisionSystem.execute(action, parameters)` dispatches via a handlers dict to `capture_screen`, `capture_region`, `read_screen_text`, `find_element`, `find_all_elements`, `describe_screen`, `compare_images`, `detect_ui_elements`, `find_text_location`, `get_screen_info`, `capture_window`, `read_clipboard`, `get_active_window_title`, `highlight_region`.
- OCR priority dispatch between tesseract and easyocr.
- Template/image matching via pyautogui.

Real and functional as a vision wrapper; its integration into the kernel/intent path is not wired from `main.py` (it is passed into `Brain` as `vision_system`).

### 2.3 `vision/screen_analyzer.py`

Large; read enough to know it is a real screen-analysis module. Not fully verified end-to-end here, but it exists as part of the vision story.

---

## 3. `workers/` — isolated worker scaffolding

### 3.1 `workers/__init__.py`

Contains only a comment: "Isolated worker processes".

### 3.2 `workers/worker_base.py` and `workers/shell_worker.py`

- Read enough to know these are worker-process scaffolding files (shell worker entry point + worker base).
- `pyproject.toml` declares a script `novamind-worker = "workers.shell_worker:main"`, so the repo intends a separate worker process entrypoint.
- These are real scaffolding but not wired into `main.py`'s current boot (the kernel worker-supervisor path is not started).

---

## 4. Skeleton signals in UI/vision/workers

- The PyQt6 UI exists but is intentionally disabled.
- Vision is real but is wired as a Brain dependency, not as a kernel adapter path.
- Workers exist as a package and an entrypoint, but the worker-supervisor/Jon-Object/import-hook isolation path is not started by `main.py`.
- The "Game UI only" choice in `main.py` leaves the desktop UI as an unused alternative, which is consistent with two competing front ends not yet resolved.
