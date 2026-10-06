# NovaMind Audit — Agents Layer, File by File

**Audit date:** 2026-10-06  
**Scope:** `agents/` tree (including `agents/apps/`).  
**Method:** files read directly; large files were read with enough coverage to characterize real behavior, imports, and handler registration.

---

## 1. `agents/__init__.py`

Empty. No package-level wiring.

---

## 2. `agents/application_agent.py`

### What it is
A universal Windows desktop automation agent. Real implementations, not stubs: it imports `pyautogui`, `pygetwindow`, `pyperclip`, `PIL`, `pytesseract`, `easyocr`, `numpy`, `subprocess`, and real helpers from `core.os_utils.os_executor` and `core.os_utils.uia_executor`.

### What it actually does
- Registers a large `self.handlers` dict (O(1) dispatch) covering `open_application`, `close_application`, `focus_window`, `click`, `type_text`, `do_task_in_app`, `click_element_by_text`, `fill_field`, `select_menu_item`, `wait_for_text`, `screenshot`, `read_screen`, `get_screen_info`, `open_folder`, `open_file_with`, `paint_task`, etc.
- `open_application` tries a priority strategy chain: Windows Search (Win key → type → Enter) → Win+R run dialog → subprocess shell.
- `do_task_in_app` runs an LLM-planning loop: each step it OCRs the screen, asks the LLM for the next action JSON, executes the action via pyautogui, and replans after repeated failures.
- `PaintAgent` is instantiated inside it and exposed as `paint_task` handler.

### Skeleton signals
- Despite being a "real" agent, its `execute` is still the `BaseAgent` handler-dispatch path; it is **not** shown being invoked through the `intent→kernel→adapter` path in `main.py`.
- It imports `subprocess` directly (allowed by comment as "last-resort shell launcher"), which is exactly what the kernel-architecture docs say must go through `KernelExecutionFacade`.

---

## 3. `agents/apps/__init__.py`

Empty aside from a comment describing the package purpose.

---

## 4. `agents/apps/paint_agent.py`

### What it is
MS Paint specialist: open, detect canvas, clear, set color via UIA "Edit Colors" dialog (automation IDs 703/704/705), select pencil, draw strokes, save, and a high-level `draw_task`.

### What it actually does
- Uses real `pyautogui`/`pygetwindow` plus `core.os_utils.os_executor` helpers (`OSExecutor`, `assert_window_focused`, `detect_paint_canvas`, `safe_drag`, `safe_click`, `safe_hotkey`, `ActionVerifier`, `FocusLostError`, `capture_region`).
- Drawing plan: tries LLM for stroke JSON; on failure falls back to a geometric sports-car drawing plan (`_car_fallback`).
- `draw_task` is the handler that `application_agent`'s `paint_task` lambda delegates to.

### Skeleton signals
- The file contains a Phase 10.5 "capability shim" (`_ModuleShim` for `subprocess`, `shutil`, `socket`). That shim exists because the kernel architecture wants to intercept those imports; the shim is itself evidence that the real capability gating is not yet the default path.
- Geometric fallback is detailed and real; the LLM path is real but depends on `LLMRouter` availability.

---

## 5. `agents/browser_agent.py`, `code_agent.py`, `data_agent.py`, `email_agent.py`, `network_agent.py`, `system_agent.py`, `file_agent.py`, `memory_agent.py`

These are each real agent modules with handler registrations and domain logic; I read enough of each to confirm:

- Each is a `BaseAgent` subclass (or intends to be).
- Each registers `self.handlers`.
- Each is imported and instantiated by `main.py`'s `_init_agents()` from a static `AGENT_CLASSES` map.
- Several of them are thin or incomplete in the parts that would connect them to the kernel/intent path; they mostly present a traditional agent API.

Because the files are individually large, the audit treats them as "real agent scaffolding" rather than fully verified end-to-end agents. The important architectural point is that **`main.py` instantiates them and passes them into `Brain`**, not into the kernel facade.

---

## 6. `agents/error_handler.py`, `agents/error_recovery_agent.py`

- `error_recovery_agent.py` is wired in `main.py` as `ErrorRecoveryAgent(event_bus=..., memory_system=...)`.
- `error_handler.py` is listed in `AGENT_CLASSES` but not separately wired into `Brain` the way `VerifierAgent` and `ErrorRecoveryAgent` are.

These are part of the "recovery/verification" story. Their existence is real; their integration depth is limited by the fact that `Brain._apply_recovery` calls `self.recovery_agent.classify_error` and `recover`, and those methods exist on the agent, but the broader kernel recovery/reconciliation path (`EffectReconciler`, `PanicManager`, `ReplayCoordinator`) is not wired from `main.py`.

---

## 7. `agents/verifier_agent.py`

- Instantiated in `main.py` as `VerifierAgent(memory_system=..., event_bus=...)`.
- Used by `Brain._run_verification` via `self.verifier.verify(...)`.
- Part of the "no silent failures" story.

Real enough as a verifier scaffold; its verification semantics are not the same as the `verification_taxonomy.py` / `verification_semantics.py` classes in `core/execution/`, which is itself a sign of two parallel verification concepts.

---

## 8. `agents/application_agent.py` vs `agents/apps/paint_agent.py`

- `application_agent.py` is the general desktop automation agent.
- `agents/apps/paint_agent.py` is the Paint specialist.
- `application_agent.py` creates `self._paint = PaintAgent()` and routes `paint_task` to it.

So Paint functionality is real and layered: `application_agent` → `PaintAgent` → `core.os_utils` UIA/OSExecutor.

---

## 9. Cross-cutting agent observation

- All agents live in a **separate package** from the kernel execution layer.
- The agents are real and detailed, especially `application_agent` and `paint_agent`.
- But in `main.py` they are wired as **direct executors**, not as intent emitters feeding a kernel. That is the core "skeleton" evidence for the agents layer: the agents exist, but the intended kernel boundary (`ExecutionIntent` → governance → scheduler → facade → adapters) is not the active path for them.
