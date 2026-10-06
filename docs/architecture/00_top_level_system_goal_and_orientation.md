# NovaMind Repository Audit — Top-Level System Goal and Orientation

**Audit date:** 2026-10-06  
**Scope:** entire repository tree (excluding `.git`, `.freebuff`, `.local` skill cache, `test_env` venv, `__pycache__`, Godot binaries in `tools/godot/`, `tools/godot_voxel_engine/`)  
**Method:** every project source file was opened and read; this document summarizes the cross-cutting findings and states the main goal. Module-level documents give per-file evidence.

---

## 1. The repo carries two different system identities

This is the single most important finding. The repository is not consistently one system; it contains **two overlapping but incompatible narratives**.

### 1.1 Identity A — "Autonomous Desktop AI Agent" (consumer framing)

Evidence:

- `README.md` (head): *"NovaMind — Autonomous Desktop AI Agent"*, *"Eyes → Brain → Hands Architecture"*.
- `SETUP.md`: framing is an assistant that *"sees your screen, understands what you ask in plain English, and takes real actions: drawing in MS Paint, running commands, searching the web, writing code."*
- `main.py` banner: `NovaMind v{__version__} — Autonomous Desktop AI ... Eyes → Brain → Hands (Multi-Agent Architecture)`.
- `config.py` is dominated by MS Paint automation constants: `PAINT_OPEN_WAIT`, `PAINT_WINDOW_POLL`, `PAINT_UIA_RED_FIELD = "703"`, `DRAWING_STROKE_MIN_PTS`, `CANVAS_SCAN_START = 80`, etc.
- `agents/application_agent.py` is a universal desktop automation agent built on `pyautogui`/`pygetwindow`/`pyperclip`/OCR, with handlers like `open_application`, `click`, `type_text`, `do_task_in_app`.
- `agents/apps/paint_agent.py` is a dedicated MS Paint drawing module (geometric sports-car fallback, LLM stroke planning).
- `requirements.txt` and `pyproject.toml` list the desktop automation + vision stack: `pyautogui`, `pygetwindow`, `pyperclip`, `comtypes`, `pywin32`, `PyQt6`, `Pillow`, `pytesseract`, `easyocr`, `opencv-python`, `ursina`.

### 1.2 Identity B — "Recoverable Distributed Runtime Kernel" (engineering framing)

Evidence:

- `README.md` (after the first heading) explicitly says:

  > NovaMind is **not** primarily an AI desktop assistant. That was an early framing that has been superseded by the actual engineering.  
  > NovaMind is a **Recoverable Distributed Runtime Kernel**

- `docs/runtime/RUNTIME_SEMANTIC_LAWS.md`: declares immutable laws ("WAL Durability Law", "Replay Safety Law", "Concurrency Law", "Capability Law", "Semantic Ownership Law", etc.).
- `docs/runtime/NOVAMIND_RUNTIME_ENGINEERING_PROTOCOL.md`: protocol for modifying a *"deterministic RuntimeKernel architecture"*.
- `runtime_snapshot.json`: a `capability_topology` document classifying capabilities by `determinism_class`, `replay_policy`, `rollback_policy`, `authority_level`, `trust_level`, `verification_mode`. Example entries: `filesystem.delete`, `process.spawn`, `shell.execute`, `ui.mouse_click`, `ui.keyboard_type`.
- `legacy_baseline.txt`: a compliance checklist saying files like `runtime/brain.py`, `runtime/capability_broker.py`, etc. *"MUST route through KernelExecutionFacade via 'shell.execute'"*.
- `core/execution/runtime_kernel.py`, `core/execution/kernel_facade.py`, `core/execution/capability_registry.py`, `core/execution/intent_execution_state.py`, `core/execution/recovery_journal.py`, `core/execution/resource_lock_manager.py`, `core/execution/verification_semantics.py`, `core/execution/verification_taxonomy.py`, `core/execution/window_lifecycle.py`, `core/execution/execution_scheduler.py`, `core/execution/execution_ordering_coordinator.py`.
- `core/runtime/kernel_supervisor.py`, `core/runtime/worker_runtime.py`, `core/runtime/worker_sandbox.py`, `core/runtime/resource_governor.py`, `core/runtime/syscall_gate.py`, `core/runtime/capability_broker.py`, `core/runtime/execution_sandbox.py`.
- `core/transaction/effect_wal.py`, `core/transaction/transaction_manager.py`, `core/transaction/effect_reconciler.py`, `core/transaction/panic_manager.py`.
- `core/replay/replay_engine.py`, `core/replay/replay_coordinator.py`, `core/replay/event_recorder.py`, `core/replay/divergence_analyzer.py`.
- `core/ipc/*` (binary framing, CBOR canonical serialization, named-pipe transport, bridge server, worker protocol).
- `core/sync/synchronization.py` (Lamport logical clock, epoch manager, snapshot barrier).
- `core/state/*` (snapshot store, state snapshot manager, runtime store, state manager).
- `core/telemetry/*`, `core/orchestration/causal_scheduler.py`, `core/orchestration/event_bus.py`, `core/orchestration/kernel_supervisor.py` (note: a second `KernelSupervisor` in `orchestration/`, distinct from the one in `runtime/`).

**Conclusion:** the deeper you go into `core/`, the more the system describes itself as a deterministic, replayable, capability-governed runtime kernel. The desktop-agent story is concentrated in `main.py`, `agents/`, `config.py`, `adapters/` (outer), `legacy_game/`, and the Godot client.

---

## 2. What the system is trying to become (intended architecture)

Based on the code, not the README, the intended architecture has these layers:

### 2.1 Kernel/execution layer (the "real" core, per the engineering docs)

- **Intents as the boundary:** `core/execution/execution_intent.py` defines `ExecutionIntent` as *"The boundary between Agent Intelligence and Kernel Execution. Agents emit Intents. They DO NOT execute them."*
- **Capability registry:** `core/execution/capability_registry.py` declares a static table of capabilities (`filesystem.read`, `process.spawn`, `ui.mouse_click`, `shell.execute`, ...) each classified by determinism/replay/rollback/authority/trust/verification.
- **Contracts:** `core/contracts/intent_contracts.py` registers per-adapter/per-operation contracts and validates intents.
- **Governance + scheduler + facade:** `core/execution/intent_governance.py`, `core/execution/execution_scheduler.py`, `core/execution/kernel_facade.py` split ordering/governance/routing.
- **State machine for intents:** `core/execution/intent_execution_state.py` defines `IntentExecutionState` with a legal transition table.
- **WAL/durability:** two distinct WAL systems exist (see section 4): `core/transaction/effect_wal.py` and `core/replay/event_recorder.py` (which contains its own `RecoveryJournal` class), plus `core/execution/recovery_journal.py` (a third `RecoveryJournal`).
- **Worker isolation:** `core/runtime/worker_sandbox.py` (Windows Job Object via ctypes), `core/runtime/worker_runtime.py` (supervisor + IPC), `core/runtime/syscall_gate.py` (import-time capability policy hook).
- **Reconciliation/panic:** `core/transaction/effect_reconciler.py`, `core/transaction/panic_manager.py`.
- **Replay:** `core/replay/replay_engine.py` reads segmented JSONL WAL, validates hash chain, submits to a `CausalScheduler`.

### 2.2 Runtime/bootstrap/authority layer

- `core/runtime/runtime_bootstrap.py` defines `BootstrapPhase.TRANSITIONAL` vs `STRICT`, and constructs `LifecycleAuthority`, `KernelSupervisor` (the `runtime/` one), `AdapterSupervisor`, `RuntimeKernel`, `RuntimeEventStream`, `RuntimeSnapshotProvider`, and freezes `SemanticAuthorityRegistry`.
- `core/runtime/lifecycle_authority.py` — sole owner of lifecycle state (`INITIALIZING`, `RECONCILING`, `READY`, `DEGRADED`, `HALTING`, `HALTED`, `PANIC`).
- `core/runtime/semantic_authority_registry.py` — enforces "exactly one owner per mutable domain".
- `core/bootstrap/runtime_lifecycle.py` — a separate FSM (`RuntimeState.BOOT → ... → READY → ... → HALT`), used by `main.py`'s `NovaMindApp.lifecycle`.

### 2.3 Agent layer

- `core/foundation/base_agent.py` — `BaseAgent` with `handlers: Dict[str, Callable]`, `EffectJournal`, O(1) dispatch via `self.handlers.get(...)`.
- `agents/*` — one agent module per domain (file, system, browser, code, application, memory, network, data, email, error_handler, verifier, error_recovery).
- `core/runtime/agent_context.py` — `AgentContext.emit_intent(...)` intended to route through `KernelExecutionFacade`.

### 2.4 IPC / bridge to Godot

- `core/ipc/bridge_server.py` — WebSocket server on `127.0.0.1:8765`, CQRS framing: Godot commands are "fire-and-forget Intent submissions", UI observations are loss-tolerant.
- `core/ipc/*` — binary framing (`NMIP` magic, 83-byte header, CRC32 + BLAKE2b), CBOR canonical serialization, named-pipe transport.
- `integrations/godot/godot_bridge_protocol.py`, `godot_transport.py`, `mission_projection.py` — the "presentation-only" Godot message types.

### 2.5 UI / observation / vision / workers

- `ui/task_window.py` — a PyQt6 task window (currently disabled in `main.py`).
- `vision/vision_system.py`, `vision/screen_analyzer.py` — screenshot/OCR/element detection wrappers.
- `workers/shell_worker.py`, `workers/worker_base.py` — isolated worker process stubs.

### 2.6 Godot client ("Nova City" spatial shell)

- `godot_client/*.gd` — Godot 4 client: `NetworkManager` (WebSocket to `ws://127.0.0.1:8765`), `Main`, `CommandHub` (voxel terrain), `Player` (first/third person), `AgentVisualizer` (holograms for task/agent events), `Terminal` (input overlay), `DiagnosticsOverlay`.
- `legacy_game/nova_mindscape.py` — a separate, far larger Ursina-based "Nova Mindscape" open-world city (this is the "3D game" referenced in `main.py`).

---

## 3. Main goal after completion (synthesized from code)

If the codebase is completed as the deeper engineering layers intend, the main goal is:

**A Windows desktop runtime that treats AI agents as untrusted workloads and executes their requested side effects through a deterministic, capability-governed, WAL-logged, replayable kernel, with a Godot (or Ursina) spatial UI that is strictly a read-only presentation layer.**

In that completed system:

- Agents propose **intents** (`ExecutionIntent`), not actions.
- A **capability registry + intent contracts** classify every operation by determinism/replay/rollback/authority/trust.
- A **kernel facade + execution scheduler + ordering coordinator** route and serialize intents; non-commutative intents must serialize.
- **WAL + fsync-before-propagation** makes intent state durable before it is propagated; replay can reconstruct pre-disruption state.
- **Worker processes** are contained by Windows Job Objects and an import-time syscall gate.
- The **presentation layer** (Godot client / Ursina mindscape / PyQt6 task window) is isolated from execution authority and may only observe projected state.
- The desktop automation story (MS Paint drawing, pyautogui clicks) is meant to become a **non-deterministic legacy bridge** — allowed, but classified as `NON_DETERMINISTIC`, `LEGACY_BRIDGE`, `HUMAN_REQUIRED` rollback, replay skipped.

**However**, the repo currently also contains a fully fleshed-out alternate path in which the "Brain" directly runs agents that call `pyautogui`/`subprocess`/OCR, and `main.py` initializes `Brain`, `LLMRouter`, `StateManager`, `CommandGuard`, `MemorySystem`, `TaskManager`, `BridgeServer`, `PermissionManager`, etc. That path is the "autonomous desktop assistant" scaffolding.

So the main goal is ambiguous by design: **there are two competing completion targets in one repository.**

---

## 4. Headline findings (proofs; details in module docs)

### 4.1 Two kernels, two supervisors, two event buses, two recovery journals

- `core/runtime/kernel_supervisor.py` — imports `WorkerSupervisor`, `EffectWal`, `EffectReconciler`, `PanicManager`, `TransactionManager`, `CausalScheduler`.
- `core/orchestration/kernel_supervisor.py` — a different class, imports `RuntimeLifecycle`, `RuntimeState`, and expects `event_bus` + `event_recorder`.
- `core/execution/recovery_journal.py` — defines `RecoveryJournal` (JSONL append + fsync).
- `core/replay/event_recorder.py` — defines **another** `RecoveryJournal` (segmented JSONL, manifest, hash chaining).
- `core/transaction/effect_wal.py` — defines **another** durable WAL (`EffectWal`, binary frames, SHA-256 chain).
- `core/orchestration/event_bus.py` — defines `RuntimeEventTopologyCoordinator` as the event bus (typed `RuntimeEvent` subclasses, fsync-before-propagation, recursion depth guard).
- `core/runtime/runtime_event_stream.py` — subscribes to the **same** `RuntimeEvent` types via `get_event_bus()`.
- `main.py` — uses a completely different, untyped bus: `from core.orchestration.event_bus import get_event_bus`, but then subscribes handlers to string event types like `"task_started"`, `"safety_check_blocked"`, and emits via `event_bus.emit_sync("session_started", {...})`. That `emit_sync` signature does **not** match `RuntimeEventTopologyCoordinator.emit_sync`, which requires a `RuntimeEvent` instance.

**Evidence:** the architecture documents describe one kernel; the code contains multiple overlapping implementations of the same concepts.

### 4.2 The "Contracts" package is mostly empty

Files under `core/contracts/`:

- `errors.py` — empty file.
- `events.py` — empty file.
- `interfaces.py` — empty file.
- `protocols.py` — empty file.
- `typing.py` — empty file.
- `runtime_states.py` — contains only `from .runtime_events import RuntimeState`, but `RuntimeEvent` is defined in `runtime_events.py`; `RuntimeState` is not defined there (it exists as `core.bootstrap.runtime_lifecycle.RuntimeState` and `core.runtime.lifecycle_authority.RuntimeLifecycleState`).

**Evidence:** `core/contracts/` is advertised by its presence as the contract layer, but the actually loaded contracts live in `core/contracts/intent_contracts.py`, `core/contracts/runtime_events.py`, `core/contracts/tool_result.py`, and `core/execution/capability_registry.py`. The rest are stubs.

### 4.3 `main.py` is the glue that exposes the skeleton nature

`main.py` does a lot of wiring, but almost all of it is wrapped in `try/except Exception as exc: logger.warning(...)`:

- EventBus init, StateManager init, Security init, Vision init, Agent init, VerifierAgent init, ErrorRecoveryAgent init, Brain init, TaskManager + BridgeServer + PermissionManager init, Scheduler init.
- If any of those fail, the app continues and reports components as present/absent in `get_status()`.

**Evidence:** `NovaMindApp.initialize()` returns `True` even when large parts of the system failed to initialize. That is consistent with a foundation/skeleton: the wiring exists, but nothing is proven to work end-to-end.

### 4.4 The "kernel execution path" is not wired end-to-end in `main.py`

`main.py`:

- Creates `Brain(...)` and uses it for task execution.
- Creates `TaskManager` + `BridgeServer` + `PermissionManager` and registers a mock async handler `on_godot_command` that calls `asyncio.create_subprocess_shell("code .", ...)`.
- Does **not** create `RuntimeBootstrap`, does **not** set `BootstrapPhase.STRICT`, does **not** inject `RuntimeKernel` + `KernelExecutionFacade` into agents.
- `AgentContext.emit_intent` falls back to `RuntimeKernel.get_instance().facade` only in `BootstrapPhase.STRICT` failure paths; in `TRANSITIONAL` it warns and does an implicit lookup.

So the "intents → kernel → adapters" path exists in `core/`, but `main.py` mostly runs the older "agents execute directly" path. The new kernel path is not the active runtime in the entry point.

### 4.5 Godot client expects one protocol; Python bridge implements another

- `godot_client/NetworkManager.gd` parses messages with fields `type`, `action`, `payload`, `timestamp`, `msg_id`, and dispatches on `msg_type` values `"EVENT"`, `"STATE_UPDATE"`, `"COMMAND"`, `"ERROR"`.
- `core/ipc/bridge_server.py` sends messages with fields `protocol_version`, `message_type`, `event_type`, `sequence_id`, `payload`, `timestamp`, `msg_id`, `correlation_id`.
- `godot_client/Terminal.gd` sends `"EVENT"` with `action = "user_command"` and `payload.text`.
- `main.py` registers a bridge handler for `"EVENT"` and reads `data.get("event_type")` and `data.get("payload", {})`.

**Evidence:** the Godot client and the Python bridge are close but not identical in message shape; the system has not reached a verified cross-process contract.

### 4.6 The "3D game" is two different things

- `legacy_game/nova_mindscape.py` is a large Ursina open-world city ("NOVA CITY") with terrain, buildings, rain, NPCs, vehicles, HUD, beacon tasks.
- `godot_client/` is a separate Godot 4 spatial shell with voxel terrain (`CommandHub`), first/third-person `Player`, agent holograms, terminal overlay, diagnostics overlay.
- `main.py` references a single "game" and has a `self.game` attribute plus `_on_game_task_update`, but the repo contains both a Godot client and an Ursina game, and `SETUP.md` only mentions the Ursina one (`pip install ursina`).

**Evidence:** the "spatial UI" story is split across two engines; it is not clear which is the intended front end for the kernel.

---

## 5. What is foundation/skeleton vs implemented

### 5.1 Clearly skeleton/stub (checked per file in module docs)

Examples with direct evidence:

- `core/contracts/errors.py`, `events.py`, `interfaces.py`, `protocols.py`, `typing.py` — empty.
- `core/adapters/__init__.py` — does not exist.
- `core/telemetry/__init__.py` — does not exist.
- `core/execution/replay_coordinator.py` — `orchestrate_replay()` ends with a comment `# Sequence logic goes here`.
- `core/replay/replay_coordinator.py` — `execute_replay_plan()` constructs intents and calls `kernel_dispatcher.dispatch(...)` if it has a `dispatch` attribute; otherwise it only logs.
- `core/execution/kernel_facade.py` `_route_adapter()` raises `RuntimeError("KernelExecutionFacade has no dispatcher injected for structural routing.")` when `self._dispatcher` is `None`.
- `core/adapters/adapter_supervisor.py` — lazy-adapter assignment; `execute_intent` creates adapters on demand from the registry.
- Several adapter `verify()`/`reconcile()` implementations return `True` without real checks.
- `integrations/godot/godot_transport.py` — queue with backpressure policies, but no actual network transport; `mission_projection.py` — pure read-only mappers with no live data source.
- `godot_client/Terminal.gd` — auto-triggers a test command 2 seconds after ready: `timer.timeout.connect(func(): _on_text_submitted("open my vscode workspace"))`.

### 5.2 Partially real (real code, limited integration)

- `core/runtime/worker_sandbox.py` — real Windows Job Object via ctypes.
- `core/os_utils/uia_executor.py` — real UIA via comtypes.
- `core/os_utils/element_finder.py` — real three-strategy finder (UIA/OCR/template).
- `core/os_utils/uipi_classifier.py` — real integrity-level queries via win32security.
- `core/os_utils/windows_job_objects.py` — another Job Object wrapper (duplicated concept with `worker_sandbox.py`).
- `core/telemetry/telemetry_bus.py`, `telemetry_sink.py`, `telemetry_event.py` — real bounded-queue telemetry with overflow policy.
- `core/transaction/effect_wal.py`, `core/replay/event_recorder.py` — real durable append with fsync.
- `core/sync/synchronization.py` — real logical clock, epoch manager, async snapshot barrier.
- `core/foundation/canonical.py` — real deterministic JSON + SHA-256 state hash.
- `core/state/snapshot_store.py`, `core/state/state_snapshot.py` — real atomic snapshot write + load with hash verification.
- `core/adapters/filesystem_adapter.py` (in `core/adapters/`) — real filesystem operations, registered in `ADAPTER_REGISTRY`.
- `core/adapters/process_adapter.py` (in `core/adapters/`) — real `subprocess.run` wrapper.
- `core/adapters/uia_lane.py`, `core/adapters/win32_lane.py`, `core/adapters/system_lane.py` — real lane implementations.
- `core/adapters/adapter_contract.py` — real `ApplicationAdapter` ABC.
- `agents/application_agent.py`, `agents/apps/paint_agent.py`, `vision/vision_system.py`, `security/command_guard.py`, `memory/memory_system.py` — substantial real implementations.
- `legacy_game/nova_mindscape.py` — large real Ursina game.
- `godot_client/*.gd` — real Godot scripts.

### 5.3 The "main loop" reality

The only orchestrated boot sequence that actually runs is `main.py` → `NovaMindApp.initialize()` → `NovaMindApp.run()`. That boot sequence:

- initializes `LLMRouter`,
- initializes `SessionRegistry`,
- initializes `MemorySystem`,
- initializes `EventBus` (the orchestration one) + `EventRecorder` + `KernelSupervisor` (the orchestration one) + `RuntimeAuditor`,
- initializes `StateManager`,
- initializes `CommandGuard`,
- initializes `VisionSystem` if Pillow available,
- initializes agents via `_init_agents()`,
- initializes `VerifierAgent`, `ErrorRecoveryAgent`,
- initializes `Brain`,
- initializes `TaskManager`, `BridgeServer`, `PermissionManager`,
- initializes `TaskScheduler`,
- optionally initializes UI (currently disabled),
- optionally runs recovery replay from `RuntimeStore` + `ReplayEngine`.

That is a real initialization sequence, but many of its parts are not connected to the deeper "kernel/intent/WAL/replay" layer that the engineering docs describe.

---

## 6. Where to read the proofs

Module-level documents with per-file evidence:

- `docs/architecture/00_top_level_system_goal_and_orientation.md` — this file.
- `docs/core/01_core_layer_file_by_file.md`
- `docs/agents/02_agents_layer_file_by_file.md`
- `docs/integrations/03_godot_and_bridge_integration.md`
- `docs/legacy/04_legacy_game_and_legacy_compat.md`
- `docs/ui_vision_workers/05_ui_vision_workers.md`
- `docs/runtime/06_runtime_lifecycle_authority_bootstrap.md`
- `docs/architecture/07_duplicate_concepts_and_contract_gaps.md`

Follow the module docs for direct quotes and line-level evidence.
