# NovaMind Audit — Core Layer, File by File (evidence-led)

**Audit date:** 2026-10-06  
**Scope:** the core modules that were read in detail or confirmed via AST.  
**Method:** direct file reads plus targeted AST checks for enum members, attribute accesses, and syntax validity.

---

## 1. Foundation

### `core/foundation/base_agent.py`

- `BaseAgent` with `handlers: Dict[str, Callable]`, `_GLOBAL_REGISTRY`, `EffectJournal` (tags effects with logical clock + epoch if sync available), `get_state`/`set_state` serialization, `execute` O(1) dispatch (`self.handlers.get(action, self._GLOBAL_REGISTRY.get(action))`), and `_run_fn` that inspects the handler signature for a `_context`/`context` param.
- Real base class, not a stub.

### `core/foundation/canonical.py`

- Real deterministic serialization: sorted keys, float rounding to 3 decimals, NaN/Inf → None, SHA-256 `state_hash`.

### `core/foundation/runtime_paths.py`

- Real runtime-root resolution: `NOVAMIND_HOME` env, `~/.novamind`, project `.novamind` fallback; `_probe_dir` does a write/unlink probe; `get_runtime_root()` is `@lru_cache(maxsize=1)`.

### `core/foundation/session_registry.py`

- Real JSON session registry with atomic temp-write + `os.fsync` + `replace`; `create_new_session`, `get_latest_session`, `mark_session_closed`.

### `core/foundation/version.py`

- Small constants file: `RUNTIME_SCHEMA_VERSION`, `WAL_SCHEMA_VERSION`, `SNAPSHOT_SCHEMA_VERSION`, `IPC_PROTOCOL_VERSION`, `WORKER_PROTOCOL_VERSION`.

---

## 2. Contracts

### `core/contracts/intent_contracts.py`

- Real: `IntentSchemaContract`, `IntentContractRegistry`, static bootstrap contracts for process/filesystem/registry/network/legacy_ui.
- `validate_intent` rejects `authority_origin == "unsafe_runtime"` and validates required/allowed payload keys and idempotency.

### `core/contracts/runtime_events.py`

- Real: `ExecutionState`, `RuntimeEvent` and subclasses (`LifecycleEvent`, `ExecutionEvent`, `VerificationEvent`, `SchedulerEvent`, `TelemetryEvent`), `PanicLevel`.
- Used by the orchestration event bus.

### `core/contracts/tool_result.py`

- Real: `ToolResult`, `Tool` ABC, `TOOL_REGISTRY` via `@register_tool`, `get_tool`.

### Empty contract files (confirmed)

- `errors.py`, `events.py`, `interfaces.py`, `protocols.py`, `typing.py` — empty.
- `runtime_states.py` — only `from .runtime_events import RuntimeState`, which fails because `RuntimeState` is not defined in `runtime_events.py`.

---

## 3. Execution

### `core/execution/capability_registry.py`

- Real: `CapabilityDefinition` dataclass, static `_CAPABILITIES` table, `CapabilityRegistry` singleton with `get`, `require` (raises `PermissionError` for unknown capability), `all_capabilities`, `requires_foreground`, `determinism_class`.
- `CAPABILITY_REGISTRY` is the module-level instance.

### `core/execution/execution_intent.py`

- Real: `ExecutionIntent` frozen dataclass, `IntentStatus`, `VerificationMode` (EXACT/STRUCTURAL/SEMANTIC/HEURISTIC/NONE), `RollbackMode`, `IntentPriority`, `IntentDeterminismLevel`, `to_dict`.

### `core/execution/intent_execution_state.py`

- Real: `IntentExecutionState(str, Enum)` with 14 members, `LEGAL_TRANSITIONS`, `TERMINAL_STATES`, `IntentStateError`, `IntentStateMachine`.
- AST member list: `CREATED, QUEUED, DISPATCHED, RUNNING, VERIFYING, COMPLETED, FAILED, COMPENSATING, COMPENSATED, ABORTED, REJECTED, ORPHANED, RECOVERING, RECONCILED`.

### `core/execution/intent_governance.py`, `intent_result.py`, `resource_lock_manager.py`, `verification_taxonomy.py`, `window_lifecycle.py`, `verification_semantics.py`

- All real: governance validates contracts; `IntentResult` frozen dataclass; `ResourceLockManager` pure mutex ownership; `verification_taxonomy.py` has its own `VerificationMode` (STRICT_STATE_VERIFICATION, SIDE_EFFECT_VERIFICATION, OBSERVATIONAL_VERIFICATION, HUMAN_CONFIRMED, BEST_EFFORT, NONE) plus `DETERMINISM_TO_ALLOWED_MODES` and `validate_verification_mode`; `window_lifecycle.py` has `WindowLifecycleTracker` singleton with HWND validity + ownership checks via ctypes and `StaleHandleError`; `verification_semantics.py` has `PassiveVerifier`, `AsyncExecutionFuture`, `VerificationCoordinator`.

### `core/execution/kernel_facade.py`

- Real gateway: `KernelExecutionFacade.execute_gateway` routes by determinism class to `_route_adapter` or `_route_legacy`.
- `_route_adapter` raises `RuntimeError("KernelExecutionFacade has no dispatcher injected for structural routing.")` when `self._dispatcher` is None — concrete evidence the facade is not usable without injection.

### `core/execution/runtime_kernel.py`

- Real: `RuntimeKernel` singleton with deprecated `get_instance()`, boot-state enum, constructor injects `lifecycle_authority`, `adapter_supervisor`, `os_supervisor`, `intent_governance`; in STRICT mode requires all injected.

### `core/execution/recovery_journal.py`

- Real: `RecoveryJournal` JSONL append + fsync, singleton writes to `.novamind/kernel/recovery.wal`, `log_transition`, `close`.

### `core/execution/execution_scheduler.py`, `execution_ordering_coordinator.py`, `com_governance.py`

- Real: `ExecutionScheduler` with priority queues per HWND, queue aging, HWND lifecycle tracking, watchdog escalation; `ExecutionOrderingCoordinator` singleton with global serialization lock; `COMApartmentExecutor` STA thread with `pythoncom.CoInitializeEx`.

### `core/execution/replay_coordinator.py` (under `core/execution/`)

- Real but unfinished: `orchestrate_replay()` ends with the comment `# Sequence logic goes here`.

### `core/execution/replay_coordinator.py` (under `core/replay/`) — separate file

- Real but has unresolved references: calls `CAPABILITY_REGISTRY.get_capability(...)`, which is not a method on `CapabilityRegistry` (AST-confirmed methods: `get`, `require`, `all_capabilities`, `requires_foreground`, `determinism_class`).

---

## 4. State

### `core/state/snapshot_store.py`, `state_snapshot.py`, `runtime_store.py`, `state_manager.py`

- All real: atomic JSON snapshot write + fsync + rename + load-time hash verification; `StateSnapshotManager` with barrier/epoch/clock; `RuntimeStore` composing event recorder + snapshot manager; `StateManager` with SQLite `dag_nodes` table and write-on-transition.

---

## 5. Replay

### `core/replay/replay_engine.py`, `event_codec.py`, `event_recorder.py`, `divergence_analyzer.py`, `replay_cursor.py`

- Real: `ReplayEngine` with `ReplayMode` enum (STRICT/DIAGNOSTIC/FORENSIC/SALVAGE), segmented JSONL reading, cryptographic hash chaining, `CausalScheduler` submission, `execute_recovery_sync`; `JsonlEventCodec`; `RecoveryJournal` (segmented, manifest, hash chaining); `DivergenceAnalyzer`; `ReplayCursor`.

---

## 6. IPC

### `core/ipc/bridge_server.py`, `frame_codec.py`, `frame_reader.py`, `frame_writer.py`, `serializer.py`, `ipc_serializer.py`, `pipe_transport.py`, `binary_transport.py`, `ipc_transport.py`, `worker_protocol.py`, `checksum.py`

- Real: WebSocket bridge with sequence/OOO/chaos/egress; binary framing with `NMIP` magic, 83-byte header, CRC32+BLAKE2b; CBOR canonical serializer with schema validation; named-pipe transport with ACL security; `IpcFrame`, `WorkerIdentity`, `FrameType`, `WorkerState`; CRC32 + BLAKE2b checksum helpers.

---

## 7. Sync, telemetry, transaction

### `core/sync/synchronization.py`

- Real: `LogicalClock`, `EpochManager`, `SnapshotBarrier` with mutation/transient gates and async context managers.

### `core/telemetry/telemetry_bus.py`, `telemetry_event.py`, `telemetry_sink.py`

- Real: bounded-queue telemetry bus with overflow policy (drop ephemeral / block critical / escalate panic), `TelemetryEvent`, `TelemetrySink` JSONL.

### `core/transaction/effect_wal.py`, `transaction_manager.py`, `effect_reconciler.py`, `panic_manager.py`

- Real: binary WAL with SHA-256 chain; `TransactionManager` with PREPARE→JOURNAL→AUTHORIZE→EXECUTE→VERIFY→COMMIT/ROLLBACK; `EffectReconciler` analyzing crash states; `PanicManager` with panic levels and lifecycle authority integration.

---

## 8. OS utils (core/)

### `core/os_utils/uia_executor.py`, `element_finder.py`, `perception.py`, `uipi_classifier.py`, `windows_job_objects.py`, `os_executor.py`

- Real: UIA via comtypes with `UIAExecutor`/`UIElement`/`UIWindow` and `set_paint_rgb`; three-strategy element finder (UIA/OCR/template); `PerceptionEngine`; integrity/UIPI classifier via win32security; another Job Object wrapper; demoted HID fallback lane.

---

## 9. Orchestration (subsets read in detail)

### `core/orchestration/causal_scheduler.py`, `event_bus.py`, `kernel_supervisor.py`, `llm_router.py`, `task_parser.py`, `step_executor.py`, `scheduler.py`, `task_manager.py`

- Real: causal DAG scheduler with logical clock + epoch + trace log; typed event bus coordinator; orchestration `KernelSupervisor` (separate from runtime/ one); multi-provider `LLMRouter`; `TaskParser` with O(1) keyword/risk/agent lookups and LLM+fallback; `StepExecutor` verify-retry loop; `TaskScheduler` priority/time-based; `TaskManager` asyncio task queue.

---

## 10. Core-layer skeleton signals

- Substantial real code across `core/`, especially execution, state, replay, IPC, transaction, sync, telemetry, os_utils, and orchestration.
- But the module graph has duplicate concepts (two supervisors, three WALs, two lifecycle controllers, two verification-mode enums, two job-object wrappers) and several unresolved references (e.g. `CapabilityRegistry.get_capability`, `IntentExecutionState.TERMINATED`, `RuntimeState` import from wrong module, `action` variable in Chrome CDP adapter).
- The deeper kernel path is implemented but not wired from `main.py`.

See `docs/architecture/07_duplicate_concepts_and_contract_gaps.md` for the cross-cutting duplicate/stub evidence.
