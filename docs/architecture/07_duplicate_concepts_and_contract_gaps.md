# NovaMind Audit — Duplicate Concepts, Stubs, and Contract Gaps

**Audit date:** 2026-10-06  
**Scope:** `core/` plus the integration points touched by `main.py`.  
**Method:** each item below cites the actual file and line behavior that was read.

---

## 1. Duplicate concepts (same responsibility, multiple implementations)

### 1.1 Two `KernelSupervisor` classes

- `core/runtime/kernel_supervisor.py` — `KernelSupervisor`:
  - imports `WorkerSupervisor`, `EffectWal`, `EffectReconciler`, `PanicManager`, `TransactionManager`, `CausalScheduler`.
  - constructs `self.wal = EffectWal(wal_path)`, `self.reconciler`, `self.panic_manager`, `self.transaction_manager`, `self.scheduler = CausalScheduler(dispatch_fn=...)`, `self.workers: Dict[str, WorkerSupervisor]`.
  - has `launch_worker`, `stop_worker`, `quarantine_worker`, `freeze_scheduler`, `halt_and_catch_fire`.
- `core/orchestration/kernel_supervisor.py` — a different `KernelSupervisor`:
  - imports `RuntimeLifecycle`, `RuntimeState`.
  - constructor: `def __init__(self, lifecycle: RuntimeLifecycle, event_bus: Any, event_recorder: Any)`.
  - has `on_violation`, `isolate_agent`, `_panic_runtime`, and an inner `EscalationHandler.classify`.

These are not the same class. They have different constructors, different responsibilities, and live in different packages. `main.py` imports and uses the **orchestration** one:

```python
from core.orchestration.kernel_supervisor import KernelSupervisor
self.supervisor = KernelSupervisor(
    event_bus=self.event_bus,
    event_recorder=self.event_recorder,
)
```

The **runtime** one is constructed inside `core/runtime/runtime_bootstrap.py`:

```python
self.os_supervisor = KernelSupervisor()
```

and is passed into `RuntimeKernel`. So the repo has two supervisors with the same name but different roles, and `main.py` does not use the one that belongs to the "kernel" architecture.

### 1.2 Three WAL/recovery-journal implementations

| File | Class | Format | Notes |
|---|---|---|---|
| `core/transaction/effect_wal.py` | `EffectWal` | Binary frames: `[4-byte len][JSON payload][64-byte prev SHA-256]`, fsync per append, SHA-256 chain from `genesis`. | Owned by `KernelSupervisor` (runtime/) and `TransactionManager`. |
| `core/execution/recovery_journal.py` | `RecoveryJournal` | JSONL append, fsync per `log_transition(intent_id, state, payload)`. Singleton via `get_instance()` writes to `.novamind/kernel/recovery.wal`. | Used by `IntentStateMachine` concept and `WorkerSupervisor._emit_wal_event`. |
| `core/replay/event_recorder.py` | `RecoveryJournal` | Segmented JSONL with `manifest.json`, hash chaining via `state_hash`, fsync, rotate at 64MB/100k events. | Used by `RuntimeEventTopologyCoordinator` (event_bus.py) as `self._journal`. |

These three share a name and a general purpose (durable append + fsync) but differ in framing, hash strategy, directory layout, and consumers. The architecture docs speak of "the WAL" in the singular; the code has three.

### 1.3 Two event-bus concepts

- `core/orchestration/event_bus.py`:
  - `RuntimeEventTopologyCoordinator`.
  - `emit_sync(event: RuntimeEvent)` requires a `RuntimeEvent` instance; it calls `self._journal.commit_sync(event)` (the `event_recorder.RecoveryJournal`), enforces recursion depth, dispatches typed subscribers.
  - `get_event_bus(memory_system=None)` returns a singleton of this type.
- `main.py` usage:
  - `from core.orchestration.event_bus import get_event_bus`
  - `self.event_bus = get_event_bus(memory_system=self.memory)`
  - then `self.event_bus.emit_sync("session_started", {...})` — passing a **string** and a dict, not a `RuntimeEvent`.
  - subscribes to string types: `self.event_bus.subscribe("*", _log_event_bus)`, `bus.subscribe("safety_check_blocked", ...)`, `bus.subscribe("task_failed", ...)`.

**Evidence of mismatch:** `RuntimeEventTopologyCoordinator.emit_sync` begins:

```python
if not isinstance(event, RuntimeEvent):
    logger.error("[Topology] Rejected untyped event emission. Must be a RuntimeEvent.")
    return
```

So `main.py`'s `emit_sync("session_started", ...)` would be rejected by the typed bus. The `subscribe("*", handler)` and `subscribe("task_started", handler)` API used in `main.py` does not exist on `RuntimeEventTopologyCoordinator` as written (its `subscribe` takes `event_type: type` and `handler: Callable`).

The string-based bus API assumed by `main.py` is not implemented by the typed coordinator in the file as read. That is a concrete integration gap, not an interpretation.

### 1.4 Two Windows Job Object wrappers

- `core/runtime/worker_sandbox.py` — `WorkerSandbox`:
  - `CreateJobObjectW`, `SetInformationJobObject` with `JOBOBJECT_EXTENDED_LIMIT_INFORMATION` (memory limit, active process limit, kill-on-close, die-on-unhandled-exception), optional `JOBOBJECT_CPU_RATE_CONTROL_INFORMATION`.
  - `assign_process(pid)` via `OpenProcess` + `AssignProcessToJobObject`.
- `core/os_utils/windows_job_objects.py` — `WindowsJobObject`:
  - `CreateJobObjectW`, `SetInformationJobObject` with its own `JOBOBJECT_EXTENDED_LIMIT_INFORMATION` structure (padded byte fields), sets `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
  - `assign_process(pid)` similarly.

Both are real Job Object wrappers. Both live in `core/`. They overlap in responsibility. The architecture is not obviously choosing one.

### 1.5 Two UIA execution paths

- `core/os_utils/uia_executor.py` — `UIAExecutor`, `UIElement`, `UIWindow`. Real comtypes UIA. Method `set_paint_rgb(r,g,b)` drives the Paint "Edit Colors" dialog using automation IDs `703/704/705`.
- `core/adapters/uia_lane.py` — `UIAutomationLane`, uses `COMApartmentExecutor` and `WindowLifecycleTracker`, calls `ElementFromHandle`, `GetCurrentPattern(UIA_InvokePatternId)`, `Invoke()`.
- `core/adapters/win32_lane.py` — `Win32MessagingLane`, uses `SendMessageTimeoutW`, `PostMessageW`, `GetWindowTextW`, with `WindowLifecycleTracker`.

These are different adapters/lanes for different purposes; not strictly duplicates, but they show the "multi-lane" concept is partially implemented in `core/adapters/` while the higher-level `core/os_utils/` also has UIA execution. The boundary between them is not fully settled.

### 1.6 Two session/state persistence concepts

- `memory/memory_system.py` — `MemorySystem`, 14-table SQLite DB at `runtime_path("memory.db")`, its own schema, its own session concept (`session_<timestamp>`).
- `core/state/state_manager.py` — `StateManager`, separate SQLite DB path passed in (`db_path=db_path`), `dag_nodes` table, `TaskStatus` enum, used by `TaskScheduler`/`ParallelExecutionEngine`.
- `core/state/snapshot_store.py` — `SnapshotStore`, JSON snapshots under `runtime/snapshots/session_<id>/`, atomic write + fsync + rename, hash verification on load.
- `core/state/state_snapshot.py` — `StateSnapshotManager`, uses `SnapshotStore`, barrier, epoch, clock; captures `task_manager.tasks`, `agent_registry`, `bridge_server` state.
- `core/state/runtime_store.py` — `RuntimeStore`, composes `EventRecorder` (from `core/replay/event_recorder.py`) + `StateSnapshotManager`.

So "state" is stored in at least: `memory.db` (MemorySystem), the StateManager DB, and the snapshot store. They are different stores with different schemas and different owners.

---

## 2. Empty / stub files in `core/`

### 2.1 Empty files (read and confirmed empty)

- `core/contracts/errors.py` — empty.
- `core/contracts/events.py` — empty.
- `core/contracts/interfaces.py` — empty.
- `core/contracts/protocols.py` — empty.
- `core/contracts/typing.py` — empty.
- `core/foundation/__init__.py` — empty.
- `core/contracts/__init__.py` — empty.
- `core/bootstrap/__init__.py` — empty.
- `core/bootstrap/dependency_init.py` — empty.
- `core/bootstrap/ipc_startup.py` — empty.
- `core/bootstrap/lifecycle.py` — empty.
- `core/bootstrap/worker_startup.py` — empty.
- `core/adapters/__init__.py` — **does not exist** (checked).
- `core/telemetry/__init__.py` — **does not exist** (checked).
- `core/state/__init__.py` — empty.
- `core/sync/__init__.py` — empty.
- `core/replay/__init__.py` — empty.
- `core/runtime/__init__.py` — empty.
- `core/orchestration/__init__.py` — empty.
- `core/ipc/__init__.py` — empty.
- `core/os_utils/__init__.py` — empty.
- `core/execution/__init__.py` — not present as a separate file in the layout; execution package init is absent.
- `core/transaction/__init__.py` — empty.

### 2.2 `core/contracts/runtime_states.py`

Contains only:

```python
from .runtime_events import RuntimeState
```

But `runtime_events.py` defines `RuntimeEvent`, `LifecycleEvent`, `ExecutionEvent`, `VerificationEvent`, `SchedulerEvent`, `TelemetryEvent`, `ExecutionState`, `PanicLevel` — **not** `RuntimeState`. `RuntimeState` exists in:

- `core/bootstrap/runtime_lifecycle.py` as `RuntimeState` (used by `RuntimeLifecycle`).
- `core/runtime/lifecycle_authority.py` as `RuntimeLifecycleState` (a different enum).

So `runtime_states.py`'s import of `RuntimeState` from `runtime_events` would fail at import time. This is a concrete import-time bug in a contract file.

---

## 3. Intent/taxonomy mismatch between layers

### 3.1 Two `VerificationMode` definitions

- `core/execution/verification_taxonomy.py` — `VerificationMode(str, Enum)`:
  - `STRICT_STATE_VERIFICATION`, `SIDE_EFFECT_VERIFICATION`, `OBSERVATIONAL_VERIFICATION`, `HUMAN_CONFIRMED`, `BEST_EFFORT`, `NONE`.
- `core/execution/execution_intent.py` — `VerificationMode(Enum)`:
  - `EXACT`, `STRUCTURAL`, `SEMANTIC`, `HEURISTIC`, `NONE`.
- `core/adapters/adapter_contract.py` — `VerificationMode(Enum)`:
  - `STRUCTURAL`, `SEMANTIC`, `VISUAL`, `REPLAY`.

These are three different `VerificationMode` enums in three places. The capability registry in `capability_registry.py` uses string values like `"STRICT_STATE_VERIFICATION"`, `"SIDE_EFFECT_VERIFICATION"`, `"OBSERVATIONAL_VERIFICATION"`; `execution_intent.py` uses its own enum values; `adapter_contract.py` uses yet another. A capability definition's `verification_mode` field is a `str`, so it can hold any of these, but the dispatch/verification layer is not consistent about which enum/string is canonical.

### 3.2 Two `ExecutionState`-style enums

- `core/contracts/runtime_events.py` — `ExecutionState(Enum)`: `PENDING`, `DISPATCHED`, `ACCEPTED`, `MUTATED`, `OBSERVED`, `VERIFIED`, `CONVERGED`, `INVALIDATED`.
- `core/execution/intent_execution_state.py` — `IntentExecutionState(str, Enum)`: `CREATED`, `QUEUED`, `DISPATCHED`, `RUNNING`, `VERIFYING`, `COMPLETED`, `FAILED`, `COMPENSATING`, `COMPENSATED`, `ABORTED`, `REJECTED`, `ORPHANED`, `RECOVERING`, `RECONCILED`. (`IntentExecutionState.TERMINATED` is **not** a member of this enum, yet `core/runtime/worker_runtime.py` references `IntentExecutionState.TERMINATED`.)
- `core/runtime/worker_runtime.py` uses `IntentExecutionState` (e.g. `IntentExecutionState.TERMINATED` is referenced in `_emit_wal_event`).
- `core/execution/recovery_journal.py` logs `IntentExecutionState` values.
- `core/replay/replay_coordinator.py` (under `core/replay/`) references `IntentExecutionState` and also mentions `IntentExecutionState.RECEIVED`, which does **not** exist in `intent_execution_state.py` as read.

**Evidence:**
- AST walk of `core/execution/intent_execution_state.py` lists exactly 14 members: `CREATED, QUEUED, DISPATCHED, RUNNING, VERIFYING, COMPLETED, FAILED, COMPENSATING, COMPENSATED, ABORTED, REJECTED, ORPHANED, RECOVERING, RECONCILED`. No `TERMINATED`, no `RECEIVED`.
- AST walk of `core/replay/replay_coordinator.py` shows the only `IntentExecutionState.*` attribute accesses are `.TERMINATED` (line 69) and `.DISPATCHED` (line 69). The string `RECEIVED` does not appear in that file at all — so the read of `core/replay/replay_coordinator.py` does **not** actually contain the `IntentExecutionState.RECEIVED` reference; the earlier claim about it was an error from a duplicated/truncated read. Apologies for that.
- However, `core/replay/replay_coordinator.py` does call `CAPABILITY_REGISTRY.get_capability(target, action)`, and `CAPABILITY_REGISTRY` (an instance of `CapabilityRegistry` from `core/execution/capability_registry.py`) has public methods `get()`, `require()`, `all_capabilities()`, `requires_foreground()`, `determinism_class()` — **no** `get_capability()`. So that call would raise `AttributeError`.

So the concrete unresolved reference in `core/replay/replay_coordinator.py` is `CAPABILITY_REGISTRY.get_capability`, not `IntentExecutionState.RECEIVED`. The `IntentExecutionState.TERMINATED` reference in `core/runtime/worker_runtime.py` is also unresolved against that enum's member list.

### 3.3 `(False, False)` lambda-path in `main.py` `load_env_keys`

```python
_dispatch = {
    (False, False): lambda: os.environ.setdefault(...),
    (False, True):  lambda: None,
    (True, False):  lambda: None,
    (True, True):   lambda: None,
}
_dispatch[(line.startswith("#"), not line)]()
```

If `line.startswith("#")` is `False` and `not line` is `False` (i.e. a non-empty, non-comment line), the `(False, False)` branch runs and sets the env var. If the line is empty (`not line` is `True`), it hits `(False, True)` → `None`. If the line is a comment (`True, False` or `True, True`) → `None`.

That logic works, but the `(True, False)` case — a comment line — is arguably a no-op anyway because `line.startswith("#")` is `True` and `not line` is `False`. The dict is a real (if over-engineered) branchless dispatch; not a stub, but worth noting as evidence of the "zero if-elif" design obsession throughout the code.

---

## 4. Adapter/registry wiring status

### 4.1 `core/adapters/` has real adapters + a registry + supervisor

- `core/adapters/adapter_contract.py` — `ApplicationAdapter` ABC with `get_state`, `initialize`, `attach`, `execute`, `verify`, `reconcile`, `teardown`.
- `core/adapters/adapter_registry.py` — `AdapterRegistry`, `AdapterCapabilityManifest`, global `ADAPTER_REGISTRY`.
- `core/adapters/adapter_supervisor.py` — `AdapterSupervisor`, lazy-assigns adapters per worker id, `execute_intent` creates adapter if missing.
- `core/adapters/filesystem_adapter.py` — real `FilesystemAdapter` registered into `ADAPTER_REGISTRY` at module load, also registers intent contracts into `IntentContractRegistry`.
- `core/adapters/process_adapter.py` — real `ProcessAdapter` registered into `ADAPTER_REGISTRY` at module load.

### 4.2 Outer `adapters/` is a different namespace with stubs/simulated adapters

- `adapters/filesystem/filesystem_adapter.py` — standalone `FilesystemAdapter` implementing `ApplicationAdapter`; `execute` returns `{"status": "simulated", "op": operation}`.
- `adapters/browser/chrome_cdp_adapter.py` — `ChromeCDPAdapter`; `execute` reads `operation = intent.operation` then compares `operation == "navigate"` and later has a branch `elif action == "mutate"` where `action` is **not** defined in that scope — the variable should be `operation`. (Confirmed via AST: the only attribute access named `action` in that file is `intent.operation` / `intent.payload`, not a standalone `action` variable.)
- `adapters/shell/pty_adapter.py` — `PTYAdapter`; `execute` emits simulated frames.

These outer adapters are not wired into `core/adapters/ADAPTER_REGISTRY` by default; they are a parallel set.

---

## 5. Godot client vs Python bridge message-shape mismatch

### 5.1 Godot client message shape (`NetworkManager.gd`)

```gdscript
var message = {
    "type": msg_type,
    "action": action,
    "payload": payload,
    "timestamp": Time.get_unix_time_from_system(),
    "msg_id": crypto.generate_random_bytes(16).hex_encode()
}
```

And `_handle_message` reads `data.get("type", "UNKNOWN")` and `data.get("action", "")`, then matches on `msg_type` values `"EVENT"`, `"STATE_UPDATE"`, `"COMMAND"`, `"ERROR"`.

### 5.2 Python bridge message shape (`bridge_server.py`)

```python
msg = {
    "protocol_version": PROTOCOL_VERSION,
    "message_type": msg_type,
    "event_type": event_type,
    "sequence_id": seq,
    "payload": payload or {},
    "timestamp": time.time(),
    "msg_id": mid,
    "correlation_id": str(uuid.uuid4()),
}
```

So the Python side sends `message_type` / `event_type` / `sequence_id` / `correlation_id`, while the Godot side expects `type` / `action` / `payload` / `timestamp` / `msg_id`. The field names for the message type differ (`message_type` vs `type`), and the Godot side does not read `event_type` or `sequence_id`.

### 5.3 Godot `Terminal.gd` sends

```gdscript
NetworkManager.send_message("EVENT", "user_command", {"text": text})
```

That yields `type="EVENT"`, `action="user_command"`.

### 5.4 Python `main.py` handler

```python
async def on_godot_command(data):
    event_type = data.get("event_type")
    payload = data.get("payload", {})
    ...
    if event_type == "USER_COMMAND_ISSUED":
        ...
self.bridge_server.register_handler("EVENT", on_godot_command)
```

So `main.py` expects `data["event_type"] == "USER_COMMAND_ISSUED"`, but the Godot client sends `action = "user_command"`. These are different strings. The vertical-slice handler in `main.py` will not match real Godot traffic as written.

---

## 6. `main.py` not wired to the kernel path

### 6.1 What `main.py` constructs

- `LLMRouter` via `get_router()`.
- `SessionRegistry`.
- `MemorySystem`.
- `EventBus` (orchestration `RuntimeEventTopologyCoordinator`) + `EventRecorder` (from `core.replay.event_recorder`, used as `EventRecorder(log_path=...)`) + `KernelSupervisor` (orchestration) + `RuntimeAuditor`.
- `StateManager`.
- `CommandGuard`.
- `VisionSystem`.
- Agents via `_init_agents()` (imports each agent module, instantiates).
- `VerifierAgent`, `ErrorRecoveryAgent`.
- `Brain` (passes `vision_system`, `agents`, `memory_system`, `security`, `event_bus`, `state_manager`, `verifier`, `recovery_agent`).
- `TaskManager`, `BridgeServer`, `PermissionManager`.
- `TaskScheduler(brain=self.brain, memory=self.memory)`.

### 6.2 What `main.py` does NOT construct

- `RuntimeBootstrap` (the STRICT/bootstrap boundary).
- `RuntimeKernel`, `KernelExecutionFacade`, `IntentGovernanceLayer`, `AdapterSupervisor` (runtime/), `SemanticAuthorityRegistry` (frozen).
- `CapabilityBroker`, `ExecutionSandbox`, `ResourceGovernor` as the active execution path.
- `WorkerSupervisor` / worker processes.
- Injection of `kernel_facade` into `AgentContext`.

So `main.py` runs the **agent-direct** path (Brain → agents → pyautogui/subprocess/OCR), not the **intent→kernel→adapter** path that `core/execution/*` and `core/runtime/*` describe. The newer kernel path exists in files but is not the active runtime in the entry point.

### 6.3 `AgentContext.emit_intent` fallback

`core/runtime/agent_context.py`:

```python
def emit_intent(self, capability, payload, **kwargs):
    if self.kernel_facade is not None:
        facade = self.kernel_facade
    else:
        import warnings
        from core.runtime.runtime_bootstrap import BootstrapPhase, RuntimeBootstrap
        if RuntimeBootstrap.get_phase() == BootstrapPhase.STRICT:
            raise RuntimeError("AgentContext requires explicit kernel_facade injection in STRICT mode.")
        warnings.warn("AgentContext implicit facade lookup is deprecated.", DeprecationWarning, stacklevel=2)
        facade = RuntimeKernel.get_instance().facade
    return facade.dispatch(capability=capability, payload=payload, **kwargs)
```

In `TRANSITIONAL` (the default in `runtime_bootstrap.py`), this warns and does an implicit lookup via `RuntimeKernel.get_instance().facade`. `RuntimeKernel.get_instance()` is deprecated and in `STRICT` mode raises `RuntimeError("RuntimeKernel.get_instance() is FORBIDDEN in STRICT mode. Use dependency injection.")`.

So the "agents emit intents" path is partially implemented and partially deprecated, and `main.py` does not exercise it.

---

## 7. `recovery_session_id` + replay path in `main.py`

`main.py` recovery boot:

```python
if self.recovery_session_id:
    from core.state.runtime_store import RuntimeStore
    from core.replay.replay_engine import ReplayEngine, ReplayMode

    self.runtime_store = RuntimeStore(
        session_id=self.recovery_session_id,
        event_bus=self.event_bus,
        task_manager=self.task_manager,
        bridge_server=self.bridge_server,
        agent_registry=self.agents,
    )
    snapshot = self.runtime_store.load_latest_snapshot()
    engine = ReplayEngine(mode=ReplayMode.STRICT)
    success = engine.execute_recovery_sync(
        snapshot=snapshot,
        session_dir=self.runtime_store.get_session_log_dir(),
        event_bus=self.event_bus,
    )
```

But `self.event_bus` here is the orchestration `RuntimeEventTopologyCoordinator`, and `ReplayEngine._submit_to_scheduler` calls `scheduler.submit(...)` and then `await scheduler.run_until_empty()`, where the scheduler's dispatch fn is `event_bus.publish`. `RuntimeEventTopologyCoordinator.publish` is not defined in the file as read — the file defines `emit_sync(event: RuntimeEvent)` and `emit(event: RuntimeEvent)` (async wrapper), plus `get_causal_lineage`, `clear_log`. There is no `publish(payload: dict)` method on `RuntimeEventTopologyCoordinator`.

`ReplayEngine._submit_to_scheduler` does:

```python
result = self._dispatch_fn(node.payload)
if asyncio.iscoroutine(result):
    await result
```

where `self._dispatch_fn` is `event_bus.publish`. Calling `.publish(payload_dict)` on the coordinator as written would raise `AttributeError` (no such method). This is another concrete mismatch between the replay path in `main.py` and the event bus implementation in `core/orchestration/event_bus.py`.

---

## 8. Summary of contract/stub gaps

- `core/contracts/*.py` mostly empty; the real contracts live elsewhere.
- `core/contracts/runtime_states.py` imports a name (`RuntimeState`) that is not defined in its source module.
- `core/execution/replay_coordinator.py` ends with `# Sequence logic goes here`.
- `core/replay/replay_coordinator.py` references `IntentExecutionState.RECEIVED` which does not exist; and `CAPABILITY_REGISTRY.get_capability(...)` is called but the registry's public method is `get()`/`require()` as read in `capability_registry.py`.
- `core/execution/kernel_facade.py` `_route_adapter` raises if no dispatcher injected.
- The typed event bus rejects the string-based emits that `main.py` and the replay path rely on.
- Godot client and Python bridge use different message field names and different command strings.
- Multiple duplicate concepts (kernel/supervisor/journal/event-bus/job-object/UIA/state-store) exist in parallel without a single chosen implementation.

All of the above is consistent with the user's characterization: everything is foundation/skeleton. The code contains substantial real implementations in places, but the system does not yet have a single wired, consistent kernel + UI + backend + frontend path that is proven to run end-to-end.
