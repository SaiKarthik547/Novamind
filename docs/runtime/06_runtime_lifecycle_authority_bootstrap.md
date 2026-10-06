# NovaMind Audit — Runtime Lifecycle, Bootstrap, Authority, and Worker Isolation

**Audit date:** 2026-10-06  
**Scope:** `core/runtime/` (lifecycle, bootstrap, authority, worker isolation), `core/bootstrap/runtime_lifecycle.py`, `core/execution/runtime_kernel.py`.  
**Method:** files read directly; enum member lists confirmed via AST where relevant.

---

## 1. Two lifecycle controllers

### 1.1 `core/bootstrap/runtime_lifecycle.py` — `RuntimeLifecycle` + `RuntimeState`

- `RuntimeState` enum (from the AST of that file): `BOOT`, `PRECHECK`, `RECOVER`, `VERIFY_WAL`, `VERIFY_WORKERS`, `START_IPC`, `START_SCHEDULER`, `READY`, `DEGRADED`, `RECOVERY`, `QUIESCING`, `PANIC`, `HALT`.
- `RuntimeLifecycle` is the "authoritative state machine for the NovaMind execution kernel" according to its docstring.
- `ALLOWED_TRANSITIONS` maps each state to a set of allowed next states; `PANIC` is allowed from any state; `HALT` is terminal.
- Used by `main.py` as `self.lifecycle = RuntimeLifecycle()` and transitioned through the boot sequence.

### 1.2 `core/runtime/lifecycle_authority.py` — `LifecycleAuthority` + `RuntimeLifecycleState`

- `RuntimeLifecycleState` enum (from AST): `INITIALIZING`, `RECONCILING`, `READY`, `DEGRADED`, `HALTING`, `HALTED`, `PANIC`.
- `LifecycleAuthority` is described as "Phase 15B: Sole owner of runtime lifecycle state."
- It has `transition_to_reconciling`, `transition_to_ready`, `transition_to_degraded`, `trigger_shutdown`, `trigger_panic`, and shutdown/panic callbacks.

These are two different lifecycle controllers with different state names and different purposes. `main.py` uses the bootstrap one; the runtime kernel path uses the `LifecycleAuthority` one via `RuntimeBootstrap`.

---

## 2. `core/runtime/runtime_bootstrap.py` — the kernel construction boundary

- Defines `BootstrapPhase.TRANSITIONAL` (default) and `BootstrapPhase.STRICT`.
- `RuntimeBootstrap.__init__` constructs:
  - `LifecycleAuthority`,
  - `KernelSupervisor()` (the runtime/ one),
  - `AdapterSupervisor(self.os_supervisor)`,
  - `IntentGovernanceLayer()`,
  - `RuntimeKernel(...)` with those injected,
  - `RuntimeEventStream()`,
  - `RuntimeSnapshotProvider(state_supplier=lambda: {})`,
  - freezes `SemanticAuthorityRegistry`,
  - transitions to ready.
- In STRICT mode it freezes the semantic authority topology and warns that legacy topology is disabled.

So the "strict kernel bootstrap" path exists and is real. `main.py` does **not** call `RuntimeBootstrap.boot()`; it builds its own lighter bootstrap. That is the clearest single piece of evidence that the kernel path is not the active runtime.

---

## 3. `core/runtime/semantic_authority_registry.py`

- Real singleton registry with `register(domain, authority)`, `freeze_topology()`, `get_owner(domain)`, `verify_ownership(domain, claimant)`, `snapshot()`, `clear_for_testing()`.
- Enforces "exactly one owner per domain"; raises `SemanticOwnershipViolation` on duplicate ownership or late registration after freeze.
- Computes a topology generation hash at freeze time.

This is a real authority-topology enforcer. In `main.py` it is not frozen or consulted; in the kernel bootstrap path it is frozen.

---

## 4. Worker isolation — real but not active in `main.py`

### 4.1 `core/runtime/worker_sandbox.py`

- Real Windows Job Object wrapper via ctypes: `CreateJobObjectW`, `SetInformationJobObject` with `JOBOBJECT_EXTENDED_LIMIT_INFORMATION` (memory limit, active process limit, kill-on-close, die-on-unhandled-exception), optional CPU rate control, `assign_process(pid)` via `OpenProcess` + `AssignProcessToJobObject`, `close()` kills the job.

### 4.2 `core/runtime/worker_runtime.py`

- `WorkerSupervisor` for a single isolated worker process: spawns `subprocess.Popen`, assigns Job Object via `WorkerSandbox`, runs IO monitor thread and watchdog thread, sends handshake SYN + capability lease, handles frames (`HANDSHAKE_ACK`, `HEARTBEAT`, `WORKER_PANIC`), and writes WAL events via `RecoveryJournal` (the `core/execution/recovery_journal.py` one).
- Uses `IntentExecutionState.TERMINATED` in `_emit_wal_event` (which is **not** a member of `IntentExecutionState` per AST — see doc 07).

### 4.3 `core/runtime/syscall_gate.py`

- Real import-time policy hook: `CapabilityPolicyHook` on `sys.meta_path`, with `BOOTSTRAP_ALLOWLIST` and `CAPABILITY_GATES` mapping modules to required capabilities; raises `ImportCapabilityViolation` for disallowed imports.
- `install_import_hook(capabilities: frozenset)` installs the hook.

### 4.4 `core/runtime/capability_broker.py`, `resource_governor.py`, `execution_sandbox.py`, `worker_sandbox.py`

- `CapabilityBroker` issues time-bound `ExecutionLease` with `Capability` enum and `ResourceBudget`.
- `ResourceGovernor` enforces budgets via psutil (duration, CPU starvation, memory, threads, children).
- `ExecutionSandbox` wraps subprocess/file ops behind lease checks.
- These are real isolation primitives. They are not wired from `main.py`; they belong to the kernel path.

---

## 5. `core/runtime/exceptions.py`

Defines `CapabilityViolation` and subclasses (`ImportCapabilityViolation`, `ProcessSpawnViolation`, `NetworkCapabilityViolation`, `FilesystemCapabilityViolation`) plus `JobAssignmentError`. Real exception hierarchy for the isolation story.

---

## 6. Skeleton signals in runtime

- Runtime isolation primitives are real (Job Object, import hook, capability broker, resource governor, worker supervisor).
- But `main.py` does not start worker processes, does not install the syscall hook, does not issue leases, and does not use `RuntimeBootstrap`. So the isolation story is implemented but not exercised by the current entry point.
- The `IntentExecutionState.TERMINATED` reference in `worker_runtime.py` is a real latent bug relative to that enum's member list (AST-confirmed).
