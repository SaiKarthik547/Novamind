# NovaMind — Autonomous Desktop AI Agent

> **"Eyes → Brain → Hands"** — NovaMind sees your screen, plans multi-step workflows in natural language, and executes them autonomously using real mouse/keyboard control, file operations, web browsing, code execution, and Windows system management.

---

## Table of Contents

1. [What is NovaMind?](#what-is-novamind)
2. [Key Capabilities](#key-capabilities)
3. [System Architecture](#system-architecture)
4. [Component Deep-Dives](#component-deep-dives)
   - [Brain (Orchestrator)](#brain-orchestrator)
   - [EventBus](#eventbus)
   - [StateManager](#statemanager)
   - [ParallelExecutionEngine](#parallelexecutionengine)
   - [TaskParser (NLU)](#taskparser-nlu)
   - [LLM Router](#llm-router)
   - [Task Scheduler](#task-scheduler)
   - [Tool Registry](#tool-registry)
5. [Agent Catalogue](#agent-catalogue)
   - [ApplicationAgent](#applicationagent)
   - [FileAgent](#fileagent)
   - [SystemAgent](#systemagent)
   - [BrowserAgent](#browseragent)
   - [CodeAgent](#codeagent)
   - [VisionSystem](#visionsystem)
   - [VerifierAgent](#verifieragent)
   - [ErrorRecoveryAgent](#errorrecoveryagent)
   - [ErrorHandler](#errorhandler)
6. [Memory System](#memory-system)
7. [Security Layer](#security-layer)
8. [UI — Task Window](#ui--task-window)
9. [3D Game — Nova Mindscape](#3d-game--nova-mindscape)
10. [O(1) Design Patterns](#o1-design-patterns)
11. [Installation & Setup](#installation--setup)
12. [Configuration](#configuration)
13. [Running NovaMind](#running-novamind)
14. [Project File Structure](#project-file-structure)
15. [Database Schema](#database-schema)
16. [Architecture Decisions & Rationale](#architecture-decisions--rationale)
17. [Extending NovaMind](#extending-novamind)

---

## What is NovaMind?

NovaMind is a fully autonomous Windows desktop AI agent written in Python. It operates on three layers simultaneously:

- **Eyes** — A VisionSystem that captures the screen, runs OCR, detects UI elements and active windows, and describes what it sees in natural language.
- **Brain** — A multi-agent orchestration engine that receives a natural language command, plans a multi-step task graph, dispatches subtasks to specialised agents in parallel, verifies every output independently, and recovers from failures automatically.
- **Hands** — A set of agents that physically operate the computer: moving the mouse, clicking, typing, opening applications, drawing in MS Paint, navigating browsers, running terminal commands, writing and executing code, and managing files.

Unlike traditional RPA (Robotic Process Automation) tools that require pre-scripted flows, NovaMind generates its own execution plan on the fly using an LLM. It adapts when things go wrong, learns from experience, and builds a persistent memory of past tasks.

### What makes it different

| Feature | Traditional RPA | LLM Chatbots | NovaMind |
|---|---|---|---|
| Plans from natural language | ✗ | ✓ (text only) | ✓ |
| Controls the real desktop | ✓ | ✗ | ✓ |
| Verifies its own output | ✗ | ✗ | ✓ |
| Recovers from failures autonomously | ✗ | ✗ | ✓ |
| Persistent memory across sessions | ✗ | ✗ | ✓ |
| Runs tasks in parallel | ✗ | ✗ | ✓ |
| Works with ANY app on Windows | ✗ | ✗ | ✓ |

---

## Key Capabilities

### Desktop Automation
- Launches any Windows application via Start menu search, Win+R, or subprocess
- Controls MS Paint: draws shapes, fills colours, types text, saves files
- Controls any app via LLM-planned + vision-verified pyautogui sequences
- Reads screen content with dual-engine OCR (Tesseract + EasyOCR)
- Clicks UI elements by visual description, ARIA label, or coordinate

### File Management
- Read, write, copy, move, delete, rename with auto-backup to trash
- ZIP/TAR/GZ/BZ2/LZMA archive creation and extraction
- File type detection via magic bytes (not extension)
- Encoding detection, binary file reading, duplicate finder
- Directory watching for changes, metadata editing, diff generation

### Web Automation
- Playwright-based browser control (Chrome/Firefox/Edge)
- Smart element location: CSS, XPath, ARIA labels, text content
- Form filling, screenshot capture, PDF export, cookie management
- Google/Bing/DuckDuckGo search with result extraction
- JavaScript injection and SPA interaction

### System Management
- Command execution (cmd.exe, PowerShell, bash)
- Process monitoring and control (list, kill, priority)
- Windows Registry read/write/delete
- Service management (start, stop, status)
- Scheduled task creation/deletion
- Audio control (volume, mute, device switching)
- Network adapter management, firewall rules
- Performance monitoring (CPU, RAM, disk, GPU)
- Windows notifications
- Startup item management

### Code Capabilities
- Write, execute, and fix Python/JavaScript code
- AST-based code analysis (issues, metrics, complexity)
- Refactoring suggestions with before/after examples
- pip package installation, virtual environment creation
- Git operations (commit, push, diff, log)
- Pylint/flake8/mypy/bandit static analysis
- Test generation and execution

### Intelligence
- Natural language understanding via LLM (Groq, Together AI, OpenRouter, Gemini, etc.)
- Multi-provider routing with automatic fallback
- Persistent 14-table SQLite memory (episodic + semantic)
- Semantic similarity search using sentence transformers
- Experience consolidation: learns general lessons from past runs
- Skill library: records successful action sequences for reuse

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           NovaMind v3.0 Architecture                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  User Input (PyQt6 UI / CLI)                                                 │
│         │                                                                    │
│         ▼                                                                    │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                     BRAIN (Orchestrator)                             │    │
│  │  • Parses request → TaskPlan via TaskParser (LLM + rule fallback)   │    │
│  │  • Validates state transitions via VALID_TRANSITIONS frozenset      │    │
│  │  • Dispatches steps to agents via O(1) dict lookup                  │    │
│  │  • Writes every transition to StateManager (SQLite checkpoint)      │    │
│  │  • Emits every transition to EventBus (observability)               │    │
│  │  • Verifies every result via VerifierAgent (isolated LLM)           │    │
│  │  • Recovers from failures via ErrorRecoveryAgent (strategy pattern) │    │
│  └────────────────────────────┬────────────────────────────────────────┘    │
│                               │                                              │
│         ┌─────────────────────┼─────────────────────────────┐               │
│         │                     │                             │               │
│         ▼                     ▼                             ▼               │
│  ┌─────────────┐    ┌──────────────────┐    ┌───────────────────────────┐  │
│  │  EventBus   │    │  StateManager    │    │  ParallelExecutionEngine  │  │
│  │  pub/sub    │    │  SQLite write-   │    │  asyncio DAG, scatter-    │  │
│  │  session    │    │  on-transition   │    │  gather, crash recovery   │  │
│  │  replay     │    │  crash recovery  │    │  timeout + retry          │  │
│  └─────────────┘    └──────────────────┘    └───────────────────────────┘  │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                         AGENT LAYER                                  │    │
│  │  ┌────────────┐ ┌────────────┐ ┌───────────────┐ ┌──────────────┐  │    │
│  │  │FileAgent   │ │SystemAgent │ │BrowserAgent   │ │CodeAgent     │  │    │
│  │  │1437 lines  │ │2122 lines  │ │(Playwright)   │ │1836 lines    │  │    │
│  │  └────────────┘ └────────────┘ └───────────────┘ └──────────────┘  │    │
│  │  ┌───────────────────┐ ┌─────────────────┐ ┌─────────────────────┐ │    │
│  │  │ApplicationAgent   │ │VerifierAgent    │ │ErrorRecoveryAgent   │ │    │
│  │  │1650 lines MS Paint│ │isolated LLM     │ │strategy pattern     │ │    │
│  │  │any Windows app    │ │conf >= 0.7      │ │dict dispatch        │ │    │
│  │  └───────────────────┘ └─────────────────┘ └─────────────────────┘ │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    INFRASTRUCTURE                                    │    │
│  │   MemorySystem (14-table SQLite)  │  SecurityLayer (frozenset O(1)) │    │
│  │   VisionSystem (OCR + Screen)     │  LLMRouter (multi-provider)     │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌──────────────────────────┐    ┌───────────────────────────────────────┐  │
│  │  PyQt6 Task UI           │    │  Nova Mindscape (Ursina 3D Game)      │  │
│  │  Floating window         │    │  Cyberpunk task visualiser            │  │
│  │  Animated status         │    │  Orbs = tasks, crystals = XP         │  │
│  └──────────────────────────┘    └───────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Data flow for a single user request

```
User types: "Draw a red car in MS Paint and save it to Desktop"
    │
    ▼
TaskParser.parse(request)
    ├── LLM NLU → structured TaskPlan JSON
    ├── Fallback: WORD_TO_TASK_TYPE inverted index (O(1))
    └── Returns TaskPlan { type=DRAWING, steps=[...], risk=SAFE }
    │
    ▼
Brain.process_request()
    ├── Security check via CommandGuard.check_command()
    ├── EventBus.emit("task_started", {...})
    ├── StateManager.update_task(PENDING → RUNNING)
    └── Thread: _run_task_execution()
            │
            ▼
        Step 1: ApplicationAgent.execute("open_paint_and_draw", {...})
            │   ├── Open MS Paint via Windows Search
            │   ├── Wait for window to appear (vision-verified)
            │   ├── LLM plans drawing steps (lines, curves, fill)
            │   ├── Execute via pyautogui (real mouse movements)
            │   └── Returns {"success": True, "output": "..."}
            │
            ▼
        VerifierAgent.verify(description, expected, actual)
            ├── Isolated LLM call (separate context, no shared state)
            ├── Checks: did the output satisfy the goal?
            ├── confidence >= 0.7 required to accept result
            └── Returns VerificationResult { satisfied=True, confidence=0.92 }
            │
            ▼
        Step 2: FileAgent.execute("info", {"path": "C:\\Users\\...\\Desktop\\car.png"})
            ├── Checks file exists and size > 0
            └── VerifierAgent confirms file was saved
            │
            ▼
        Brain finalise:
            ├── StateManager.update_task(RUNNING → COMPLETED)
            ├── EventBus.emit("task_completed", {...})
            ├── MemorySystem.store_experience({...})
            └── UI notified via callback
```

---

## Component Deep-Dives

### Brain (Orchestrator)

**File:** `core/brain.py`

The Brain is the central coordinator. It is NOT a simple sequential executor — it is a **state machine** with verified, event-driven step execution.

#### State machine

```python
VALID_TRANSITIONS: Dict[ExecutionStatus, frozenset] = {
    PENDING:   frozenset({RUNNING, CANCELLED}),
    RUNNING:   frozenset({SUCCESS, FAILED, RETRYING, NEEDS_CONFIRMATION, CANCELLED}),
    RETRYING:  frozenset({RUNNING, FAILED, CANCELLED}),
    ...
}
```

Every transition is validated against this frozenset table before it is applied. Invalid transitions are silently rejected — the task can never enter an impossible state. This prevents races where two threads might try to transition the same task simultaneously.

#### What happens on every state transition

```python
def _transition(self, exec_: TaskExecution, new_status: ExecutionStatus, data: Dict):
    allowed = VALID_TRANSITIONS.get(exec_.status, frozenset())
    if new_status not in allowed:
        return False                                   # Rejected
    exec_.status = new_status
    self.state_manager.update_task(task_id, ...)       # SQLite checkpoint
    self.event_bus.emit_sync(new_status.value, {...})  # Observability
    self._notify(exec_)                                # UI callback
    return True
```

Three things happen atomically on every transition:
1. The state is updated in memory
2. It is written to SQLite immediately (crash recovery)
3. It is emitted on the EventBus (all subscribers notified)

#### Agent dispatch (O(1), zero if-else)

```python
def _call_agent(self, exec_: TaskExecution, step: TaskStep) -> Dict:
    agent_obj = self.agents.get(step.agent)   # O(1) dict lookup
    if agent_obj is None:
        return {"success": False, "error": f"Agent not found: {step.agent}"}
    ...
    result = agent_obj.execute(step.action, step.parameters)
```

The `agents` dict maps `"file_agent"` → `FileAgent()`, `"browser_agent"` → `BrowserAgent()`, etc. Routing is a single hash table lookup with no branching.

#### Per-step verification and recovery loop

```python
for attempt in range(self.MAX_RETRIES):
    result_data = self._call_agent(exec_, step)         # Execute
    if result_data["success"] and self.verifier:
        vr = self.verifier.verify(...)                  # Independent verify
        if not vr.satisfied:
            result_data["success"] = False              # Reject if not confident
    if result_data["success"]:
        return StepResult(SUCCESS, ...)
    if self.recovery_agent and attempt < MAX_RETRIES - 1:
        self._apply_recovery(exec_, step, error, attempt)  # Modify step params
```

---

### EventBus

**File:** `core/event_bus.py`

The EventBus is NovaMind's **central nervous system for observability**. Every significant event in the system flows through it. This decouples components completely — the Brain doesn't need to know which UI components or logging systems exist; it just emits events.

#### Required events (contract)

```python
REQUIRED_EVENTS = frozenset({
    "task_started", "task_completed", "task_failed", "task_retrying",
    "tool_call_start", "tool_call_end", "tool_call_error",
    "llm_call_start", "llm_call_end",
    "agent_handoff", "agent_spawned", "agent_terminated",
    "memory_read", "memory_write",
    "safety_check_passed", "safety_check_blocked",
    "human_escalation_required",
    "session_started", "session_ended",
})
```

Any subsystem can subscribe to any of these events without modifying the emitting code.

#### Session replay

The EventBus stores a complete chronological log of every event in memory. This enables full session replay for debugging:

```python
events = bus.replay_session(session_id="abc123")
# Returns every event in the order it was emitted, with timestamps
```

#### Persistence

Every emitted event is also written to the SQLite `system_events` table via `MemorySystem.log_system_event()`, so the event history survives process restarts.

#### Thread safety

Both `emit()` (async, for asyncio callers) and `emit_sync()` (sync wrapper, for threaded code) are available. The subscriber list is protected by a `threading.Lock()`. If a sync handler returns a coroutine, it is scheduled on the running event loop.

---

### StateManager

**File:** `core/state_manager.py`

The StateManager implements **write-on-every-transition checkpointing**. Every time a task node changes state, the change is immediately written to SQLite. If NovaMind crashes mid-task, the full task graph can be reconstructed from the database.

#### SQLite table: `dag_nodes`

```sql
CREATE TABLE dag_nodes (
    id           TEXT NOT NULL,
    session_id   TEXT NOT NULL,
    description  TEXT,
    agent_type   TEXT,
    tool         TEXT,
    args         TEXT,
    depends_on   TEXT,
    status       TEXT DEFAULT 'pending',
    retry_count  INTEGER DEFAULT 0,
    result       TEXT,
    error        TEXT,
    updated_at   TEXT,
    PRIMARY KEY (id, session_id)
)
```

This table lives inside the same `~/.novamind/memory.db` as all other NovaMind tables, so all historical data is in one place.

#### Crash recovery

```python
def load_session_state(self, session_id: str) -> List[Dict]:
    """Reconstruct DAG from database. All PENDING/RUNNING nodes restart."""
    rows = conn.execute(
        "SELECT * FROM dag_nodes WHERE session_id=?", (session_id,)
    )
    return [dict(r) for r in rows]
```

On restart, any `RUNNING` nodes from a previous session are treated as `FAILED` and their ErrorRecoveryAgent strategies are applied.

---

### ParallelExecutionEngine

**File:** `core/parallel_engine.py`

While the Brain uses threads for backward compatibility, the ParallelExecutionEngine provides a pure asyncio DAG executor for workflows that explicitly need maximum parallelism.

#### How DAG execution works

```
Task Graph:
    A ─── C
    B ─╯  │
          D ─── E

Execution:
  Round 1: A, B run simultaneously (no dependencies)
  Round 2: C runs (A+B done)
  Round 3: D runs (C done)
  Round 4: E runs (D done)
```

At each iteration, the engine finds all nodes whose dependencies are complete and `asyncio.gather()`s them. Newly unblocked nodes launch immediately as their predecessors finish.

#### Blocking agent support

Since existing agents have blocking `execute()` methods, they are wrapped in `run_in_executor()` so they don't block the event loop:

```python
@staticmethod
async def _execute_agent(agent, node: TaskNode) -> Any:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: agent.execute(node.tool, node.args),
    )
```

---

### TaskParser (NLU)

**File:** `core/task_parser.py`

The TaskParser converts raw natural language into a structured `TaskPlan` containing an ordered list of `TaskStep` objects, each specifying which agent to call, which action to invoke, and what parameters to pass.

#### Two-path parsing

1. **LLM path (primary):** Sends the request to the LLM with a detailed system prompt that describes all available agents, their capabilities, and required JSON output format. Parses the JSON response into a TaskPlan.

2. **Rule-based fallback (secondary):** If the LLM fails or returns unparseable JSON, the rule-based fallback activates. This uses two O(1) data structures:

#### O(1) task type detection: inverted index

```python
# Built once at module load from _TASK_TYPE_KEYWORDS:
WORD_TO_TASK_TYPE: Dict[str, TaskType] = {
    "file": TaskType.FILE_OPERATION,
    "folder": TaskType.FILE_OPERATION,
    "browser": TaskType.BROWSER_ACTION,
    "draw": TaskType.DRAWING,
    # ... ~60 words total
}

def _detect_task_type_fast(self, request: str) -> TaskType:
    for word in request.split():
        task_type = WORD_TO_TASK_TYPE.get(word)  # O(1)
        if task_type:
            return task_type
    return TaskType.UNKNOWN
```

The old implementation iterated over every task type's keyword list for every word in the request — O(n×k). The new implementation is O(words_in_request) with O(1) per word.

#### O(1) risk assessment: priority-ordered frozensets

```python
_RISK_KEYWORD_SETS = [
    (RiskLevel.CRITICAL, frozenset(["delete", "format", "registry", ...])),
    (RiskLevel.HIGH,     frozenset(["install", "overwrite", ...])),
    (RiskLevel.MEDIUM,   frozenset(["execute", "download", ...])),
    (RiskLevel.LOW,      frozenset(["create", "rename", ...])),
]

def _assess_risk_fast(request: str) -> RiskLevel:
    rl = request.lower()
    for level, kws in _RISK_KEYWORD_SETS:     # Exits on first match
        if any(k in rl for k in kws):         # frozenset O(1) per check
            return level
    return RiskLevel.SAFE
```

#### Drawing fast-path

Requests matching both a drawing keyword (`draw`, `paint`, `sketch`, ...) AND a Paint keyword (`ms paint`, `mspaint`, ...) are handled directly without LLM invocation, generating a pre-configured `TaskPlan` with `open_paint_and_draw` action.

#### Application task fast-path

Requests like "do X in Word" or "open Chrome and navigate to Y" are matched against a list of 40+ known application names and directly generate an `application_agent.do_task_in_app` step.

---

### LLM Router

**File:** `core/llm_router.py`

The LLM Router provides a unified interface to multiple AI providers with automatic failover, rate limit handling, and cost tracking.

#### Supported providers

| Provider | Best for | Free tier |
|---|---|---|
| Groq | Speed (Llama 3.3 70B, 300 RPM) | Yes |
| Together AI | Long context, code | Yes |
| OpenRouter | Access to 100+ models | No |
| xAI (Grok) | General reasoning | No |
| Google Gemini | Vision, multimodal | Yes |
| Hyperbolic | Cheap inference | Yes |
| NVIDIA NIM | Enterprise models | No |
| Cerebras | Ultra-fast inference | Yes |

#### Task-type routing

Different task types route to different models:
- `quick` tasks → fastest available model (Groq Llama)
- `coding` tasks → code-specialised model (DeepSeek Coder, CodeLlama)
- `general` tasks → balanced model (Mixtral 8×7B, Llama 3.3 70B)
- `vision` tasks → multimodal model (Gemini Pro Vision)

#### Automatic failover

If the primary provider returns an error, rate limit, or timeout, the router automatically tries the next provider in priority order without the caller needing to handle this.

---

### Task Scheduler

**File:** `core/scheduler.py`

The TaskScheduler manages a priority queue of pending tasks. It runs as a background thread that continuously polls the queue and submits ready tasks to the Brain.

Features:
- Priority levels (0-10, higher = sooner)
- Recurring tasks with cron-like scheduling
- Dependency tracking between tasks
- Rate limiting to prevent Brain overload
- History of completed/failed submissions

---

### Tool Registry

**File:** `core/tool_result.py`

The Tool Registry provides a **decorator-based auto-registration system** that eliminates all tool-routing if-else chains.

#### Registering a tool

```python
@register_tool("browser_screenshot")
class BrowserScreenshotTool(Tool):
    description = "Take a screenshot of the current browser page"
    risk_level = 0

    async def execute(self, args: Dict) -> ToolResult:
        start = time.time()
        path = args.get("path", "screenshot.png")
        # ... implementation ...
        return self._result(success=True, output=path, start_ms=start)
```

The `@register_tool("name")` decorator adds the class to `TOOL_REGISTRY["browser_screenshot"]` automatically at import time.

#### Dispatching a tool (O(1))

```python
tool = get_tool("browser_screenshot")  # Dict lookup, no if-else
result: ToolResult = await tool.execute({"path": "out.png"})
```

#### ToolResult contract

Every tool returns a standardised `ToolResult` dataclass:

```python
@dataclass
class ToolResult:
    success: bool           # Did it work?
    output: Any             # The actual result data
    error: Optional[str]    # Error message if failed
    execution_time_ms: int  # How long it took
    tool_name: str          # Which tool produced this
    metadata: Dict          # Extra context (tokens used, retries, etc.)
```

`bool(tool_result)` is `True` iff `success` is `True`, so results can be used directly in conditionals.

---

## Agent Catalogue

### ApplicationAgent

**File:** `agents/application_agent.py` (1,650 lines)

The ApplicationAgent is the most complex agent. It controls ANY Windows desktop application using a combination of:
1. LLM-planned action sequences
2. pyautogui for mouse/keyboard execution
3. VisionSystem for verification
4. OCR for reading screen text

#### Application launch strategy (most reliable first)

```
1. Windows Search  →  Win key → type app name → Enter
2. Win+R Run dialog → for known executables
3. subprocess.Popen → direct exe path as last resort
```

The Windows Search approach is preferred because it works for every installed application, even if the executable path is unknown.

#### MS Paint drawing

When asked to draw something in MS Paint, the agent:
1. Launches MS Paint via Windows Search
2. Waits for the canvas to appear (vision-verified)
3. Asks the LLM to generate a detailed drawing plan (which shapes to draw in what order, what colours to use, where on the canvas)
4. Executes the plan via pyautogui mouse drag sequences
5. Sets colours by OCR-locating the colour picker, not hardcoded tab counts
6. Saves the file using Ctrl+S or File → Save As

The drawing is real — actual mouse movements on the actual MS Paint canvas, not image API calls.

#### Dynamic app control

For generic app tasks (`do_task_in_app`), the agent:
1. Launches the app
2. Takes a screenshot and describes the current state
3. Asks the LLM: "Given this screen state, what is the next action to achieve: [task]?"
4. Executes the suggested action (click, type, scroll, etc.)
5. Retakes a screenshot and repeats until done or max_steps reached
6. Every action is followed by a visual verification step

#### pyautogui safety settings

```python
pyautogui.FAILSAFE = True   # Move mouse to corner to abort
pyautogui.PAUSE    = 0.03   # 30ms between every action
```

Both settings are always enforced — there is no way to disable FAILSAFE.

---

### FileAgent

**File:** `agents/file_agent.py` (1,437 lines)

Complete file system management with auto-backup safety net.

#### Supported actions

| Action | Description |
|---|---|
| `read` | Read text file with encoding detection |
| `write` | Write text file (overwrite or append) |
| `copy` | Copy file or directory tree |
| `move` | Move with conflict resolution |
| `delete` | Move to trash (~/.novamind/trash) before deletion |
| `search` | Regex/glob file search across directories |
| `info` | Full metadata (size, dates, permissions, hash) |
| `list` | Directory listing with metadata |
| `archive` | Create ZIP/TAR/GZ archive |
| `extract` | Extract any supported archive format |
| `diff` | Line-by-line diff between two files |
| `watch` | Watch directory for changes |
| `find_duplicates` | MD5-based duplicate finder |
| `detect_type` | Magic-byte file type detection |
| `read_binary` | Read and decode binary file structure |

#### Protected paths

Destructive operations on these paths are blocked unconditionally:
`C:\Windows`, `C:\Program Files`, `/usr/bin`, `/etc`, `/sys`, `/dev`, `/proc`, `/boot`

#### Auto-backup

Every destructive operation (delete, move, overwrite) first copies the original to `~/.novamind/trash/{timestamp}_{filename}` before proceeding. This provides one-level undo for all file operations.

---

### SystemAgent

**File:** `agents/system_agent.py` (2,122 lines)

Full Windows/Linux/macOS system control.

#### Supported operations

- **Processes:** list, kill, set priority, get info by PID or name
- **Commands:** execute cmd/PowerShell/bash with timeout, streaming output
- **Registry:** read/write/delete keys and values (Windows)
- **Services:** start, stop, pause, query status (Windows)
- **Scheduled tasks:** create, delete, list, run-now (Windows)
- **Event log:** query application/system/security logs (Windows)
- **Firewall:** add/remove/list rules (Windows)
- **Performance:** CPU/RAM/disk/network counters, GPU usage
- **Audio:** get/set volume, mute/unmute, list devices, switch output
- **Display:** get/set resolution, refresh rate, brightness
- **Printers:** list, set default, print file
- **Network:** list adapters, get/set IP, DNS configuration
- **Power:** sleep, hibernate, restart, shutdown with delay
- **Notifications:** Windows toast notifications
- **Startup:** add/remove startup items

#### Security blocking patterns

The following patterns are blocked unconditionally regardless of user instruction:
```
format c:  |  del /f/s  |  rm -rf /  |  rd /s /q c:\
reg delete HKLM...system  |  net user .../delete
takeown .../system32  |  bcdedit  |  diskpart
```

---

### BrowserAgent

**File:** `agents/browser_agent.py`

Playwright-based browser automation for web tasks.

#### Supported actions

- `navigate` — go to URL, wait for load
- `search` — perform web search (Google, Bing, DuckDuckGo) and extract results
- `click` — click element by CSS, XPath, text, or ARIA label
- `fill` — fill input field with text
- `screenshot` — capture current page state
- `extract_text` — get text content of elements
- `scroll` — scroll page or element
- `wait` — wait for element, navigation, or condition
- `evaluate` — execute JavaScript in page context
- `download` — download file from URL
- `pdf` — export page as PDF
- `cookies` — get/set/clear browser cookies

#### Smart element location

The BrowserAgent tries multiple strategies to find elements before giving up:
1. CSS selector
2. XPath
3. ARIA label text
4. Visible text content
5. Role + accessible name
6. Visual position (falls back to VisionSystem)

---

### CodeAgent

**File:** `agents/code_agent.py` (1,836 lines)

Full-stack code intelligence.

#### Core capabilities

- **Write code:** Generate Python, JavaScript, TypeScript, Bash from natural language description
- **Execute code:** Run in sandboxed subprocess with timeout and output capture
- **Analyse code:** AST-based issue detection, complexity metrics, security scanning
- **Fix code:** Given an error message + code, generate a targeted fix
- **Refactor:** Extract functions, rename variables, split classes, reduce complexity
- **Test:** Generate unit tests, run pytest/unittest, report coverage
- **Git:** commit, push, pull, diff, log, branch management
- **Packages:** pip install, requirements.txt management, venv creation
- **Profile:** cProfile execution, identify bottlenecks

#### Execution safety

Python code runs in a subprocess (never via eval/exec in the main process). Memory limit is enforced where supported. Execution timeout is configurable (default: 30s). Output is captured and returned; exceptions do not propagate to the caller.

---

### VisionSystem

**File:** `vision/vision_system.py`

Eyes for the entire system. All visual operations go through here.

#### Capabilities

- **Screenshot:** full screen or specific window/region
- **OCR:** dual-engine (Tesseract + EasyOCR) with confidence scoring
- **Screen description:** LLM-powered description of what is visible
- **Element detection:** find clickable elements, input fields, buttons by description
- **Image comparison:** structural similarity, change detection between screenshots
- **Window management:** get active window title, list windows, focus/minimize
- **Template matching:** find image within image (OpenCV matchTemplate)
- **Color analysis:** extract dominant colors from screen region

#### When VisionSystem is used

The VisionSystem is called:
- By `ApplicationAgent` to verify app launched and canvas changed
- By `VerifierAgent.verify_gui_action()` for visual diff verification
- By `BrowserAgent` as element location fallback
- By `Brain` to populate context before parsing (active window title)
- Directly when the task type is `vision_analysis`

---

### VerifierAgent

**File:** `agents/verifier_agent.py`

The VerifierAgent is the most critical agent for reliability. It is invoked after every tool execution to independently confirm that the output satisfied the goal.

#### Why a separate verifier?

Without independent verification, a multi-agent system suffers from **collective delusion** — agents reinforce each other's incorrect conclusions. By using a completely separate LLM call with no shared context, the VerifierAgent provides an objective second opinion.

The producing agent and the verifying agent:
- Use separate LLM calls with separate conversation contexts
- Never see each other's chain-of-thought
- May use different models (verifier intentionally uses a "skeptical" temperature of 0.1)

#### Verification prompt

```python
VERIFICATION_PROMPT = """You are an independent verification agent.
You were NOT involved in producing this output. Evaluate objectively.

Task Goal: {task_description}
Tool Used: {tool_name}
Expected Output Pattern: {expected_output}
Actual Output: {actual_output}

Respond in JSON ONLY:
{
  "satisfied": true_or_false,
  "confidence": 0.0_to_1.0,
  "issues": ["list of problems"],
  "evidence": "what specifically proves success or failure",
  "next_action": "continue|retry|escalate|abort",
  "retry_strategy": "if retry: what to do differently"
}"""
```

#### Confidence threshold

Even if the LLM responds `"satisfied": true`, the VerifierAgent forces `satisfied = False` if `confidence < 0.7`. This prevents hallucinated success confirmations from propagating.

#### Visual verification

For GUI tasks, `verify_gui_action()` compares before/after screenshots using structural similarity. If similarity > 0.99 (nothing changed), the action is considered failed.

---

### ErrorRecoveryAgent

**File:** `agents/error_recovery_agent.py`

The ErrorRecoveryAgent implements the **strategy pattern** for automatic failure recovery. When the VerifierAgent rejects a result, the Brain calls the ErrorRecoveryAgent to get a modified version of the failed task.

#### Strategy dispatch (zero if-else)

```python
RECOVERY_STRATEGIES: Dict[str, List[StrategyFn]] = {
    "element_not_found": [
        _try_alternative_selector,    # attempt 0
        _try_visual_location,         # attempt 1
        _try_pyautogui_fallback,      # attempt 2
    ],
    "timeout": [
        _retry_doubled_timeout,       # attempt 0
        _break_into_smaller_steps,    # attempt 1
        _try_alternative_tool,        # attempt 2
    ],
    "command_failed": [...],
    "llm_schema_mismatch": [...],
    "paint_drawing_failed": [...],
    "generic": [...],
}

async def recover(self, error_type: str, context: Dict, attempt: int) -> RecoveryPlan:
    strategies = RECOVERY_STRATEGIES.get(error_type, RECOVERY_STRATEGIES["generic"])
    strategy_fn = strategies[min(attempt, len(strategies) - 1)]  # Index, no if-else
    return await strategy_fn(RecoveryContext(...))
```

The dispatch is a dict lookup + list index. The error type determines which strategy list to use. The attempt number determines which strategy within that list to try. No branching.

#### Error type classification

The error message text is matched against frozenset keyword groups to determine the error type:

```python
ELEMENT_KEYWORDS = frozenset({"element", "not found", "selector", ...})
TIMEOUT_KEYWORDS = frozenset({"timeout", "timed out", "deadline", ...})
...
```

#### When escalation happens

If all strategies for an error type are exhausted AND the error recurs, the final strategy is `_escalate()`, which emits `"human_escalation_required"` on the EventBus and logs a critical-severity entry in the error log.

---

### ErrorHandler

**File:** `agents/error_handler.py`

The ErrorHandler provides LLM-assisted error analysis and fix suggestion. It is distinct from the ErrorRecoveryAgent — the ErrorHandler analyses and explains errors; the ErrorRecoveryAgent modifies task parameters to retry them.

#### Severity classification

```python
SEVERITY_SETS = [
    ("critical", frozenset({"fatal", "crash", "corrupt", "segmentation", ...})),
    ("high",     frozenset({"permission", "access denied", "connection refused", ...})),
    ("medium",   frozenset({"timeout", "not found", "unavailable", ...})),
    ("low",      frozenset({"warning", "deprecated", ...})),
]
```

Priority-ordered scan stops at first match. frozenset membership is O(1).

---

## Memory System

**File:** `memory/memory_system.py` (1,024 lines)

NovaMind uses a 14-table SQLite database at `~/.novamind/memory.db`.

### Tables

| Table | Purpose |
|---|---|
| `sessions` | One row per NovaMind session (start/end time, metadata) |
| `tasks` | One row per user task (request, status, risk, timing) |
| `task_steps` | One row per step within a task (agent, action, result) |
| `agent_actions` | Low-level action log (every agent.execute() call) |
| `memories` | Episodic experiences (embedding + text, semantic search) |
| `learning_journal` | Lessons derived from task outcomes |
| `skills` | Successful action sequences stored for reuse |
| `error_log` | All errors with type, severity, resolution |
| `screenshots` | Base64-encoded screenshots linked to tasks/steps |
| `llm_calls` | Every LLM API call (provider, model, tokens, duration) |
| `user_preferences` | Key-value user preferences (typed: bool/int/float/json) |
| `ui_events` | UI interaction log |
| `system_events` | EventBus persistence (every emitted event) |
| `dag_nodes` | StateManager task graph checkpoints |

### Semantic search

If `sentence-transformers` is installed, the MemorySystem encodes every stored experience as a 384-dimensional embedding vector and performs cosine similarity search. Without sentence-transformers, it falls back to a TF-IDF-style text similarity calculation.

```python
# Find tasks similar to current request
similar = memory.find_similar_experiences(
    "draw a car in paint",
    limit=3,
    success_only=True
)
```

### Experience consolidation

After 20+ successful experiences of the same task pattern, the MemorySystem can extract a general lesson using the LLM:

```python
lesson = memory.consolidate_experiences(
    "draw.*paint",
    successful_outputs=[...]
)
# Returns: "To draw in MS Paint, always wait for the window to fully load
# before interacting. Use clipboard paste for text to avoid encoding issues."
```

### Skill library

Successful multi-step sequences are stored as reusable skills:

```python
memory.upsert_skill(
    name="draw_sports_car_paint",
    description="Draw a coloured sports car in MS Paint",
    trigger_patterns=["draw car", "paint car", "sports car"],
    action_sequence=[...],  # The exact steps that worked
    success_rate=0.95,
)
```

On the next similar request, the TaskParser checks the skill library first.

---

## Security Layer

**File:** `security/command_guard.py`

All agent actions pass through the CommandGuard before execution.

### O(1) blacklisting

```python
BLACKLIST_EXACT: frozenset = frozenset({
    "rm -rf /", "format c:", ":(){ :|:& };:", "mkfs",
    "dd if=/dev/zero of=/dev/sda",
})

BLACKLIST_CONTAINS: frozenset = frozenset({
    "> /dev/sda", "> /dev/hd", "chmod 777 /",
    "rd /s /q c:\\", "reg delete", "net user /delete",
    "bcdedit", "diskpart", ...
})

def is_blacklisted(command_lower: str) -> bool:
    return (command_lower in BLACKLIST_EXACT               # O(1)
            or any(b in command_lower for b in BLACKLIST_CONTAINS))
```

`frozenset.__contains__` is an O(1) hash lookup in CPython. The previous implementation was a for-loop over a list of regex patterns — O(n×len(command)).

### Protected paths

```python
PROTECTED_PATHS: frozenset = frozenset({
    "c:\\windows", "c:\\program files",
    "/usr/bin", "/usr/sbin", "/bin", "/sbin",
    "/etc", "/sys", "/dev", "/proc", "/boot",
})
```

Any write/delete operation to a path that starts with one of these strings is blocked.

### Risk levels

```python
RISK_PATTERNS: Dict[int, frozenset] = {
    RISK_CRITICAL: frozenset({"delete system", "format", ...}),
    RISK_HIGH:     frozenset({"install", "change permission", ...}),
    RISK_MEDIUM:   frozenset({"download", "execute", ...}),
    RISK_LOW:      frozenset({"create", "rename", ...}),
}
```

Risk is assessed in priority order (CRITICAL → HIGH → MEDIUM → LOW) and returns on first match.

### Python sandbox

The CommandGuard includes an AST-based Python code validator that rejects code using dangerous imports (`os`, `subprocess`, `socket`, ...) or dangerous calls (`eval`, `exec`, `open`, ...).

### Confirmation flow

Actions rated `RISK_HIGH` or above are blocked until the user explicitly approves them via `confirm_action(confirmation_id)`. Approved actions are added to the session allowlist.

---

## UI — Task Window

**File:** `ui/task_window.py`

A frameless, always-on-top PyQt6 window that floats over the desktop.

### Components

**Title bar:** Drag-to-move, NovaMind branding, animated status indicator, minimise/maximise/close buttons.

**Input area:** Full-width text input with placeholder examples. Submit via Enter or the Send button.

**Quick actions:** One-click preset buttons for common tasks (Draw Car, System Stats, Web Search, etc.).

**Task list:** Scrollable card list showing all submitted tasks with:
- Task ID, status badge (colour-coded), timestamp
- Summary text
- Step progress bar (n/total steps)
- Error messages in red if any steps failed

**Console:** Live log output with coloured text by log level (info/success/warning/error/debug/step).

**Status bar:** Current system state + live clock.

### Minimised state

When minimised, the window hides and a pulsing **FloatingOrb** appears in the bottom-right corner. The orb:
- Pulses with an animated radial gradient
- Shows a badge with the number of active tasks
- Changes colour based on overall system state (cyan = running, red = failed, green = all done)
- Can be dragged to any screen position
- Click to restore the main window

### System tray

NovaMind also creates a system tray icon with a context menu for Show/Hide and Quit.

---

## 3D Game — Nova Mindscape

**File:** `game/nova_mindscape.py`

An optional Ursina-based 3D game that runs in a background thread and visualises NovaMind's tasks in real time.

### Scene layout

```
                    [Neon Signs: NOVAMIND AI | TASK ENGINE | SCHEDULER]

    [Buildings]   ┌────────────────────────────────────┐   [Buildings]
                  │    Task Orbs orbiting above core   │
                  │         ↓ ↓ ↓ ↓ ↓                 │
                  │     ┌──────────────┐               │
   [Pedestal]─────┤     │  AI Core     │─────[Pedestal]│
   Running        │     │  (pulsing)   │     Done      │
                  │     └──────────────┘               │
   [Pedestal]─────┤                     ─────[Pedestal]│
   Failed         │         ●  ●  ●          Queued    │
                  │      XP crystals                   │
                  └────────────────────────────────────┘
                            [Pedestal: Total]

                  [Grid floor with neon lines]
```

### Task orbs

Each active task appears as a glowing sphere orbiting the central AI Core:
- **Cyan** = running (pulses rapidly, has spinning ring)
- **Green** = success/done (steady glow)
- **Red** = failed (dim)
- **Yellow** = retrying (pulsing)
- **Grey** = pending/cancelled

Orbs orbit at different radii and heights to avoid overlap. Running orbs pulse in size at 5Hz.

### Interaction

| Control | Action |
|---|---|
| WASD / Arrow keys | Move around the plaza |
| Mouse | Look around |
| Left click | Shoot pulse — inspect the nearest orb |
| R | Manual task refresh |
| T | Toggle task feed panel |
| M | Toggle minimap |
| ESC | Quit game |

Shooting a task orb displays its full details in the inspect panel: task ID, status, request summary, step count, error messages.

### XP Crystals

30 collectible crystals are scattered around the plaza. Walking near one collects it and adds to your XP score. Crystals spin and bob up and down. Collected crystals respawn after 60 seconds.

### Minimap

A 2D overhead minimap in the corner shows the player position, building outlines, and task orb positions using colour-coded dots.

---

## O(1) Design Patterns

NovaMind's architecture is built around a strict rule: **no if-elif chains for routing or dispatch**. Every dispatch point uses an O(1) alternative.

### Pattern inventory

| Pattern | Used in | Replaces |
|---|---|---|
| **Dict dispatch** | Brain agent routing, all agent `execute()` methods, TaskParser task type detection, all action handler tables | `if agent == "file": ... elif agent == "browser": ...` |
| **frozenset membership** | Security blacklists, risk pattern sets, valid state transitions, error severity classification | `if any(p in cmd for p in list_of_patterns)` |
| **Strategy pattern** | ErrorRecoveryAgent recovery strategies | `if error_type == "timeout": ... elif error_type == "element_not_found": ...` |
| **Decorator registry** | `@register_tool("name")` → TOOL_REGISTRY dict | Manual tool list maintenance + if-else routing |
| **State machine** | Brain VALID_TRANSITIONS table | Ad-hoc status string comparisons |
| **match/case** | CommandGuard AST sandbox (Python 3.10+) | Nested if-isinstance chains |
| **Inverted index** | WORD_TO_TASK_TYPE in TaskParser | O(n×k) nested iteration |
| **Priority-ordered frozensets** | Risk assessment, severity classification | Multi-level if-elif with list.any() |

### Why this matters

Beyond performance, these patterns make the code:
- **Extensible:** Adding a new agent means adding one key to a dict, not modifying a dispatch chain.
- **Testable:** Every routing table is a data structure that can be inspected and tested in isolation.
- **Readable:** The routing logic is visible in one place (the dict/frozenset) rather than scattered across branching code.
- **Safe:** The state machine table makes illegal transitions impossible — you can see all valid paths at a glance.

---

## Installation & Setup

### Prerequisites

- Python 3.10+ (required for `match/case` syntax)
- Windows 10/11 recommended (Linux/macOS supported with reduced functionality)
- At least one LLM API key (see [Configuration](#configuration))

### Install Python dependencies

```bash
# Core dependencies (required)
pip install requests pillow numpy pyqt6

# Vision
pip install pytesseract easyocr opencv-python sentence-transformers

# Desktop automation
pip install pyautogui pygetwindow pyperclip

# Browser automation
pip install playwright
playwright install chromium

# System monitoring
pip install psutil

# 3D game (optional)
pip install ursina

# Code analysis (optional)
pip install pylint flake8 mypy bandit

# OCR engine (external)
# Windows: https://github.com/UB-Mannheim/tesseract/wiki
# Linux:   sudo apt install tesseract-ocr
```

### API key setup

```bash
python main.py --setup
```

This creates `~/.novamind/.env`. Edit it and uncomment your key(s):

```bash
GROQ_API_KEY=your_groq_key_here          # Free, fast, recommended
TOGETHER_API_KEY=your_together_key_here  # Good for code tasks
GEMINI_API_KEY=your_gemini_key_here      # Free tier available
```

Any one key is enough to start. Multiple keys enable automatic failover.

### Verify installation

```bash
python main.py --status
```

This prints a JSON status report showing which components loaded successfully and which dependencies are missing.

---

## Configuration

### `~/.novamind/.env`

```bash
# LLM Providers (any one is sufficient)
GROQ_API_KEY=...
TOGETHER_API_KEY=...
OPENROUTER_API_KEY=...
XAI_API_KEY=...
GEMINI_API_KEY=...
HYPERBOLIC_API_KEY=...
NVIDIA_API_KEY=...
CEREBRAS_API_KEY=...
```

### `GameConfig` (in `game/nova_mindscape.py`)

```python
@dataclass
class GameConfig:
    title:        str   = "Nova Mindscape — NovaMind 3D"
    fullscreen:   bool  = False
    vsync:        bool  = True
    dev_mode:     bool  = True
    window_size:  tuple = (1280, 720)
    fov:          int   = 80
    move_speed:   float = 6.0
    look_speed:   float = 40.0
```

### Brain constants

```python
Brain.MAX_RETRIES    = 3    # Max attempts per step
Brain.STEP_TIMEOUT   = 120  # Seconds before step is killed
Brain.MAX_CONCURRENT = 3    # Max parallel tasks
```

### Security mode

```python
guard = CommandGuard(strict_mode=True)  # Require confirmation for ALL risky patterns
guard = CommandGuard(strict_mode=False) # Only block RISK_HIGH+ without confirmation
```

---

## Running NovaMind

### Full mode (GUI + 3D game)

```bash
python main.py
```

Opens the PyQt6 floating task window and the Ursina 3D game in a background thread.

### GUI only (no 3D game)

```bash
python main.py --no-game
```

### Headless mode (no GUI, CLI task)

```bash
python main.py --headless --task "Draw a blue sports car in MS Paint"
python main.py --headless --task "Search for Python tutorials on YouTube"
python main.py --headless --task "List all files in my Downloads folder"
python main.py --headless --task "Write and run a Python script that generates Fibonacci numbers"
python main.py --headless --task "Show current CPU and RAM usage"
```

In headless mode, the task runs and the agent waits up to 5 minutes for completion, printing live status updates.

### System status

```bash
python main.py --status
```

### Create API key template

```bash
python main.py --setup
```

---

## Project File Structure

```
novamind/
│
├── main.py                    # Entry point, NovaMindApp wiring
│
├── core/
│   ├── brain.py               # State machine orchestrator
│   ├── event_bus.py           # Async pub/sub, session replay
│   ├── parallel_engine.py     # asyncio DAG runner
│   ├── state_manager.py       # SQLite write-on-transition checkpoints
│   ├── task_parser.py         # NLU: request → TaskPlan
│   ├── tool_result.py         # ToolResult contract + @register_tool registry
│   ├── llm_router.py          # Multi-provider LLM routing
│   └── scheduler.py           # Priority queue task scheduler
│
├── agents/
│   ├── application_agent.py   # Desktop app control (MS Paint, etc.)
│   ├── file_agent.py          # File/folder management
│   ├── system_agent.py        # System commands, registry, services
│   ├── browser_agent.py       # Playwright web automation
│   ├── code_agent.py          # Code write/execute/fix/analyse
│   ├── verifier_agent.py      # Independent LLM output verifier
│   ├── error_recovery_agent.py# Strategy-pattern failure recovery
│   ├── error_handler.py       # LLM-assisted error analysis
│   ├── email_agent.py         # Email composition/sending
│   ├── data_agent.py          # Data analysis/transformation
│   └── network_agent.py       # Network operations
│
├── memory/
│   └── memory_system.py       # 14-table SQLite episodic/semantic memory
│
├── security/
│   └── command_guard.py       # frozenset blacklist, risk assessment, sandbox
│
├── vision/
│   └── vision_system.py       # Screenshot, OCR, element detection
│
├── ui/
│   └── task_window.py         # PyQt6 floating animated task UI
│
├── game/
│   └── nova_mindscape.py      # Ursina 3D cyberpunk task visualiser
│
├── replit.md                  # Architecture quick-reference (for agents)
├── README.md                  # This file
│
└── ~/.novamind/               # Runtime data directory
    ├── .env                   # API keys
    ├── memory.db              # SQLite database (14 tables)
    ├── trash/                 # Auto-backup before destructive operations
    └── logs/                  # Daily log files
```

---

## Database Schema

All data lives in `~/.novamind/memory.db`. Key tables:

### `tasks`
```sql
task_id TEXT PRIMARY KEY,
request TEXT,          -- Original user request
status TEXT,           -- pending/running/success/failed/cancelled
task_type TEXT,        -- file_operation/browser_action/drawing/...
risk_level TEXT,       -- safe/low/medium/high/critical
summary TEXT,
total_steps INTEGER,
steps_ok INTEGER,
steps_fail INTEGER,
started_at TEXT,       -- ISO timestamp
completed_at TEXT,
error_summary TEXT
```

### `memories`
```sql
id INTEGER PRIMARY KEY,
content TEXT,          -- Serialised experience JSON
memory_type TEXT,      -- episodic/semantic/procedural
task TEXT,             -- What was being attempted
success INTEGER,       -- 0 or 1
embedding BLOB,        -- 384-dim float32 vector
metadata TEXT,         -- Extra JSON context
timestamp TEXT
```

### `error_log`
```sql
id INTEGER PRIMARY KEY,
task_id TEXT,
agent TEXT,
action TEXT,
error_type TEXT,       -- permission/filesystem/network/dependency/value/general
error_msg TEXT,
traceback TEXT,
severity TEXT,         -- low/medium/high/critical
resolved INTEGER,      -- 0 or 1
resolution TEXT,
context TEXT,
timestamp TEXT
```

---

## Architecture Decisions & Rationale

### Why SQLite instead of a vector database?

NovaMind is a desktop agent, not a cloud service. SQLite requires zero infrastructure, zero configuration, and works offline. The 14-table schema handles all NovaMind's data needs in a single file. For vector search, we store raw float32 embeddings in a BLOB column and compute cosine similarity in Python — fast enough for thousands of memories.

### Why threading instead of pure asyncio?

All existing agents have synchronous blocking `execute()` methods (pyautogui, subprocess, Playwright sync API). Rewriting them all as async would be a massive refactor with high regression risk. The current approach uses threads for backward compatibility and wraps blocking calls in `run_in_executor()` where asyncio is needed (ParallelExecutionEngine).

### Why EventBus instead of direct callbacks?

Direct callbacks create tight coupling: every component that wants to know about task state changes must be explicitly wired up. The EventBus allows any component to subscribe to any event without the emitting component knowing who the subscribers are. This makes adding new observability (new UI, logging, game visuals) trivial — just subscribe.

### Why frozenset instead of list for blacklists?

A `frozenset` stores elements in a hash table. `"rm -rf /" in frozenset_of_patterns` is an O(1) hash lookup. `"rm -rf /" in list_of_patterns` is an O(n) scan. For security checks that run on every single agent action, this matters. frozensets are also immutable — they cannot be accidentally modified at runtime.

### Why the Verifier must be isolated?

The producing agent (e.g. ApplicationAgent) has full context of what it just tried to do, its internal state, and the actions it took. If we ask it "did that work?", it may rationalise a failure as a success. The VerifierAgent has NO access to the producing agent's context, chain-of-thought, or history. It only sees the task description, what was expected, and what actually happened. This is the same principle as code review — you review it fresh, not while you wrote it.

### Why the state machine over a simple status field?

Without transition validation, tasks can enter impossible states. Two threads could simultaneously try to move a task from `PENDING` to both `RUNNING` and `CANCELLED`. The `VALID_TRANSITIONS` frozenset table makes illegal transitions impossible to execute, regardless of concurrency. The complete set of valid paths is visible in one data structure rather than scattered across conditional logic.

### Why decorator registry for tools?

Adding a new tool to the system requires adding exactly one decorated class — no editing of dispatch code anywhere. The registry is self-documenting (inspect `TOOL_REGISTRY` to see all tools). Tools can be loaded dynamically (plugin-style) simply by importing their module.

---

## Extending NovaMind

### Adding a new agent

1. Create `agents/my_agent.py` with a class that has an `execute(action: str, parameters: Dict) -> Dict` method
2. Add `"my_agent": ("agents.my_agent", "MyAgent")` to `AGENT_CLASSES` in `main.py`
3. Add the agent's keywords to `AGENT_MAPPING` in `core/task_parser.py`
4. Done — the Brain will route tasks to it automatically

### Adding a new tool to the registry

```python
# In any file that gets imported at startup:
from core.tool_result import register_tool, Tool, ToolResult

@register_tool("my_new_tool")
class MyNewTool(Tool):
    description = "Does something new"
    risk_level = 1

    async def execute(self, args: Dict) -> ToolResult:
        import time
        start = time.time()
        result = do_the_thing(args["input"])
        return self._result(success=True, output=result, start_ms=start)
```

### Adding a new EventBus subscriber

```python
bus = get_event_bus()
bus.subscribe("task_completed", lambda event: send_notification(event["data"]))
```

### Adding a new error recovery strategy

```python
# In agents/error_recovery_agent.py:
async def _my_new_strategy(ctx: RecoveryContext) -> RecoveryPlan:
    args = dict(ctx.original_task.get("args", {}))
    args["my_flag"] = True
    return RecoveryPlan(
        strategy_name="my_strategy",
        modified_task={**ctx.original_task, "args": args},
        description="Try with my_flag enabled",
    )

# Then add to the strategies dict:
RECOVERY_STRATEGIES["my_error_type"] = [
    _my_new_strategy,
    _generic_fallback,
]
```

### Adding a new LLM provider

Add the provider's configuration to the providers dict in `core/llm_router.py` following the existing pattern. The router handles failover automatically.

---

*NovaMind is designed to be a foundation, not a finished product. Every component is built to be replaced, extended, and improved. The architecture explicitly separates concerns so that improving one component (e.g. switching to a better OCR engine) requires changing only one file.*
