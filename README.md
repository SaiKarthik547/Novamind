# NovaMind — Recoverable Distributed Runtime Kernel

> A deterministic, event-driven runtime kernel that orchestrates AI agents as first-class workloads. Built for temporal correctness, causal scheduling, and authoritative state recovery after disruption.

**Version:** 4.0.0 (Phase 7 — Concurrency Determinism & Causal Scheduling)
**Platform:** Windows 10/11 (Python 3.12+)
**License:** Apache 2.0

---

## What NovaMind Actually Is

NovaMind is **not** primarily an AI desktop assistant. That was an early framing that has been superseded by the actual engineering.

NovaMind is a **Recoverable Distributed Runtime Kernel** — a system capable of:

- **Deterministic execution**: events are ordered by causal dependencies and Lamport logical clocks, not wall-clock arrival time
- **Epoch-sealed snapshots**: state is captured in discrete temporal windows, eliminating mid-transition ambiguity
- **Authoritative recovery**: the runtime can reconstruct its exact pre-disruption state from a snapshot + delta replay
- **Split-brain detection**: Python runtime and Godot visualization client are continuously reconciled using divergence scoring
- **Tiered concurrency barriers**: mutation isolation during snapshots without global stop-the-world freezes

AI agents are **workloads** executed by the kernel — not the kernel's identity.

```
NovaMind Runtime Kernel
└── AI Agent Orchestration Runtime
    └── Specialized workload agents (file, browser, system, data, email, ...)
```

---

## Table of Contents

1. [Runtime Architecture](#runtime-architecture)
2. [Phase 7: Concurrency Determinism](#phase-7-concurrency-determinism)
3. [Recovery Semantics](#recovery-semantics)
4. [Agent Workloads](#agent-workloads)
5. [Quick Start](#quick-start)
6. [Project Structure](#project-structure)
7. [CI / Certification](#ci--certification)
8. [Development](#development)

---

## Runtime Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                   NovaMind Runtime Kernel v4.0                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │              SYNCHRONIZATION LAYER (Phase 7)                  │  │
│  │                                                               │  │
│  │  LogicalClock (Lamport)   EpochManager   SnapshotBarrier      │  │
│  │  • monotonic tick         • epoch seal   • mutation_gate      │  │
│  │  • Lamport merge rule     • advance()    • read-only bypass   │  │
│  └───────────────────┬───────────────────────────────────────────┘  │
│                      │                                              │
│  ┌───────────────────▼───────────────────────────────────────────┐  │
│  │              CAUSAL SCHEDULER (Phase 7)                       │  │
│  │                                                               │  │
│  │  • DAG dependency resolution (many-to-many causal_parents)   │  │
│  │  • Logical clock arbitration for concurrent events           │  │
│  │  • SchedulerTraceLog: why/when/how each event dispatched     │  │
│  │  • Deadlock detection + resolution without hanging           │  │
│  └───────────────────┬───────────────────────────────────────────┘  │
│                      │                                              │
│  ┌───────────────────▼───────────────────────────────────────────┐  │
│  │              RUNTIME SUPERVISOR (Phase 6)                     │  │
│  │                                                               │  │
│  │  FSM: NORMAL → DEGRADED → RECOVERY → CRITICAL_HALT           │  │
│  │  EscalationHandler  HealthEvaluator  DivergenceAnalyzer       │  │
│  └───────────────────┬───────────────────────────────────────────┘  │
│                      │                                              │
│  ┌───────────────────▼───────────────────────────────────────────┐  │
│  │              EVENT SYSTEM                                     │  │
│  │                                                               │  │
│  │  EventBus (pub/sub)    EventRecorder (JSONL journal)          │  │
│  │  RuntimeAuditor        ReplayEngine (DAG-based)               │  │
│  └───────────────────┬───────────────────────────────────────────┘  │
│                      │                                              │
│  ┌───────────────────▼───────────────────────────────────────────┐  │
│  │              SNAPSHOT & RECOVERY (Phase 6)                    │  │
│  │                                                               │  │
│  │  StateSnapshotManager  SnapshotStore  EffectJournal           │  │
│  │  • Epoch-sealed capture               • epoch_id + clock tag  │  │
│  │  • Barrier-protected atomic commits   • irreversible effects  │  │
│  └───────────────────┬───────────────────────────────────────────┘  │
│                      │                                              │
│  ┌───────────────────▼───────────────────────────────────────────┐  │
│  │              AGENT WORKLOADS                                  │  │
│  │                                                               │  │
│  │  Brain  →  TaskParser  →  Agent Dispatch (O(1) dict)          │  │
│  │  ApplicationAgent  SystemAgent  FileAgent  CodeAgent          │  │
│  │  DataAgent  NetworkAgent  EmailAgent  BrowserAgent            │  │
│  │  VerifierAgent  ErrorRecoveryAgent  MemoryAgent               │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌──────────────────────────┐   ┌─────────────────────────────┐    │
│  │ WebSocket Bridge Server  │   │ Godot Client (visualization) │    │
│  │ PRODUCTION / CHAOS mode  │   │ read-only spatial observer   │    │
│  └──────────────────────────┘   └─────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

**Invariant:** Godot is a visualization client only. It never caches authoritative logic. Every reconciliation event is logged. No silent healing.

---

## Phase 7: Concurrency Determinism

Phase 7 addresses the hardest correctness problem in distributed execution: **temporal ordering under concurrency**.

### Problem

Under async concurrency, events arrive in non-deterministic wall-clock order. Two events that are causally ordered (B must follow A) may land in the journal as B, A due to scheduler timing. Linear replay of such a log produces wrong state.

### Solution: Logical Clocks + Causal DAG

Every event and side-effect is tagged with:

```python
{
  "msg_id":        "...",
  "logical_clock": 1042,       # Lamport clock value at submission
  "epoch_id":      7,          # Which snapshot epoch this belongs to
  "causal_parents": ["..."]    # IDs of events that must complete first
}
```

The `CausalScheduler` builds a dependency DAG from these fields. Events are dispatched only when all their parents have completed, in ascending `logical_clock` order for concurrent events.

### Tiered Snapshot Barriers (not stop-the-world)

| Layer | Blocked during snapshot? |
|---|---|
| Mutation commits (agent writes) | **YES** — drained before seal |
| FSM state transitions | **YES** — deferred |
| Read-only observers (metrics) | NO |
| Heartbeat publication | NO |
| Logging and audit trails | NO |
| External IO (already in-flight) | Journaled by EffectJournal |

### Epoch Model

```
epoch N opens
  → mutations tagged epoch N
  → SnapshotBarrier enters draining mode
  → in-flight mutations complete
  → snapshot seals epoch N with state_hash + logical_clock
epoch N+1 opens immediately
```

This eliminates the mid-transition ambiguity that causes partial state captures.

### Key Phase 7 Files

| File | Purpose |
|---|---|
| `core/synchronization.py` | `LogicalClock`, `EpochManager`, `SnapshotBarrier` |
| `core/causal_scheduler.py` | DAG scheduler + `SchedulerTraceLog` |
| `core/replay_engine.py` | DAG-based replay (backward-compatible with Phase 6 logs) |
| `core/state_snapshot.py` | Epoch-sealed snapshot manager |
| `core/base_agent.py` | `EffectJournal` with epoch+clock tagging |

---

## Recovery Semantics

NovaMind's recovery model guarantees:

1. **Snapshot**: at any point, the authoritative runtime state can be captured atomically (barrier-protected, epoch-sealed, SHA-256 hashed)
2. **Delta Replay**: events that occurred after the last snapshot are replayed through the `CausalScheduler` DAG in correct causal order
3. **Equivalence**: `execute(events) → hash` must equal `replay(snapshot + delta_events) → hash` under any concurrency timing

This is validated by `tests/test_replay_equivalence.py`:
- deterministic event sequences
- randomized async yields
- snapshot + delta recovery scenarios
- Phase 6 backward-compatible log format

### Replay Validation (4-Layer)

```bash
python tools/replay_validator.py <session.jsonl>
```

| Layer | What it checks |
|---|---|
| L1 Structural | Required fields, no duplicate msg_ids |
| L2 Temporal | Causal parent ordering, legal FSM transitions |
| L3 Semantic | Reconstructed task states match last heartbeat |
| L4 Hash | Per-checkpoint SHA-256 is reproducible |

---

## Agent Workloads

Agents are workloads managed by the kernel. Each agent inherits from `BaseAgent`, uses O(1) dict dispatch (no if/elif chains), and logs side-effects to `EffectJournal` tagged with epoch and logical clock.

| Agent | Domain |
|---|---|
| `ApplicationAgent` | Desktop app control, MS Paint drawing, window management |
| `SystemAgent` | Process, registry, services, firewall, audio, display, power |
| `FileAgent` | Read/write/copy/move, archives, search, duplicate detection |
| `DataAgent` | CSV/Excel/JSON/SQL/Parquet, safe formula eval, statistics |
| `NetworkAgent` | Port scanning, DNS, HTTP, SSL, WiFi, traceroute |
| `EmailAgent` | SMTP/IMAP, attachments, threading, OAuth2 |
| `CodeAgent` | Python/JS execution, AST analysis, git, testing |
| `BrowserAgent` | URL navigation, form interaction, web search |
| `VerifierAgent` | Independent LLM verification after every action |
| `ErrorRecoveryAgent` | Strategy-pattern failure recovery and escalation |
| `MemoryAgent` | SQLite-backed episodic/semantic memory |
| `PaintAgent` | MS Paint shape drawing, color fill, canvas detection |

### Agent Execution Flow

```
User request
  │
  ▼
TaskParser.parse()  →  LLM NLU + O(1) keyword fallback
  │
  ▼
Brain.process_request()
  ├── CommandGuard.check()           # O(1) frozenset security check
  ├── EventBus.emit("task_started")
  ├── CausalScheduler.submit()       # tag with epoch + logical_clock
  └── Agent dispatch (dict lookup)
        │
        ├── Agent executes
        ├── EffectJournal.record_effect()   # epoch + clock tagged
        ├── VerifierAgent.verify()          # independent LLM check
        └── EventBus.emit("task_completed") # journaled by EventRecorder
```

---

## Quick Start

### Installation

```bash
cd Novamind
pip install -r requirements.txt
playwright install chromium   # for BrowserAgent
```

### Configuration

```bash
# Create config and add at least one LLM key
python main.py --setup

# Edit ~/.novamind/.env
GROQ_API_KEY=gsk_...     # free, fast (recommended)
```

### Run

```bash
python main.py
```

### Example Tasks

```
"Draw a red sports car in MS Paint and save to Desktop"
"Send email to john@example.com with agenda.pdf attached"
"Scan localhost for open ports"
"Show CPU and RAM usage"
"Read sales.csv and show revenue by region"
"List all Python files on Desktop"
"Write a Python quicksort and run it"
```

---

## Project Structure

```
Novamind/
├── main.py                      # Entry point
├── config.py                    # Central constants (O(1) lookups)
├── requirements.txt
│
├── core/                        # Runtime kernel
│   ├── synchronization.py       # LogicalClock, EpochManager, SnapshotBarrier [Phase 7]
│   ├── causal_scheduler.py      # DAG scheduler + SchedulerTraceLog [Phase 7]
│   ├── replay_engine.py         # Causal DAG-based replay [Phase 7]
│   ├── state_snapshot.py        # Epoch-sealed snapshot manager [Phase 6+7]
│   ├── runtime_supervisor.py    # FSM supervisor + escalation [Phase 6]
│   ├── divergence_analyzer.py   # Split-brain health scoring [Phase 5]
│   ├── canonical.py             # Deterministic SHA-256 hashing
│   ├── event_bus.py             # Pub/sub + session replay
│   ├── event_recorder.py        # JSONL event journal
│   ├── runtime_auditor.py       # Violation detection
│   ├── bridge_server.py         # WebSocket IPC (PRODUCTION/CHAOS)
│   ├── task_manager.py          # Task lifecycle tracking
│   ├── brain.py                 # Orchestrator state machine
│   ├── task_parser.py           # NLU + O(1) fallback
│   ├── base_agent.py            # Agent base + EffectJournal
│   ├── llm_router.py            # Multi-provider LLM routing
│   ├── state_manager.py         # SQLite checkpointing
│   ├── os_executor.py           # pyautogui + focus guards
│   ├── uia_executor.py          # Windows UI Automation
│   └── scheduler.py             # Task scheduling
│
├── agents/                      # Agent workloads
│   ├── application_agent.py
│   ├── system_agent.py
│   ├── file_agent.py
│   ├── code_agent.py
│   ├── data_agent.py
│   ├── network_agent.py
│   ├── email_agent.py
│   ├── browser_agent.py
│   ├── verifier_agent.py
│   ├── error_recovery_agent.py
│   ├── memory_agent.py
│   └── apps/paint_agent.py
│
├── tests/
│   ├── test_core.py                   # Core unit tests
│   ├── test_split_brain_recovery.py   # Phase 6 recovery tests
│   ├── test_async_concurrency.py      # Phase 7 barrier + scheduler tests
│   └── test_replay_equivalence.py     # Phase 7 hash equivalence tests
│
├── tools/
│   └── replay_validator.py            # 4-layer deterministic validation
│
├── godot_client/                # Visualization client (read-only)
│   ├── Main.tscn
│   ├── NetworkManager.gd
│   └── Terminal.gd
│
└── .github/workflows/
    └── runtime_certification.yml      # CI: 43-test certification suite
```

---

## CI / Certification

Every push to `main` runs the **NovaMind Runtime Certification** suite:

```yaml
- Run Deterministic Validation Suite   # test_core.py + test_split_brain_recovery.py
- Run Phase 7 Concurrency & Replay     # test_async_concurrency.py + test_replay_equivalence.py
- Run Schema Validator                  # 4-layer replay_validator.py
```

**Current status: 43/43 tests passing.**

The Phase 7 test suite verifies:
- Lamport clock correctness (tick, merge, snapshot)
- Epoch advancement (sealed on success, no advance on abort)
- Snapshot barrier: mutations drain before seal, new mutations blocked during freeze
- 100 concurrent mutations with zero state tearing
- CausalScheduler: clock ordering, single/many-to-many parents, deadlock detection
- Replay equivalence under deterministic and randomized timing
- Snapshot + delta recovery produces identical canonical hash

---

## Development

### Run Tests

```bash
pytest tests/ -v
```

### Adding a New Agent Workload

1. Create `agents/my_agent.py` inheriting from `core.base_agent.BaseAgent`
2. Populate `self.handlers` dict with `action_name → callable` (no if/elif)
3. Use `self.effect_journal.record_effect(...)` for any irreversible side-effect
4. Register in `Brain`'s agent dict
5. Add tests

### Debugging Replay Divergence

1. Check `SchedulerTraceLog` entries — every dispatch decision is recorded
2. Run `tools/replay_validator.py <session.jsonl>` for 4-layer validation
3. Compare canonical hashes at epoch boundaries
4. Look for events with missing `causal_parents` — these become causally independent and may reorder

### Key Design Rules

- **Godot must never cache authoritative logic** — it is a visualization client only
- **No silent healing** — every reconciliation event must be logged
- **Every effect is journaled** — `EffectJournal` tags epoch + logical clock
- **Determinism is verified, not assumed** — `test_replay_equivalence.py` is the ground truth

---

## License

Apache License 2.0 — See LICENSE file for details.

---

**NovaMind v4.0** — Recoverable Distributed Runtime Kernel. 43 tests. Deterministic replay. Epoch-sealed snapshots. Causal scheduling.
