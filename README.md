# NovaMind — Autonomous Desktop AI Agent

> **"Eyes → Brain → Hands"** — NovaMind sees your screen, understands natural language requests, plans complex multi-step workflows, and executes them autonomously using real mouse/keyboard control, file operations, web browsing, code execution, data manipulation, email management, network operations, and Windows system control.

**Version:** 3.0.0  
**Platform:** Windows 10/11 (Python 3.8+)  
**License:** Apache 2.0

---

## Table of Contents

1. [Overview](#overview)
2. [Complete Agent System](#complete-agent-system)
3. [Core Architecture](#core-architecture)
4. [Quick Start](#quick-start)
5. [Detailed Capabilities](#detailed-capabilities)
6. [System Components](#system-components)
7. [Project Structure](#project-structure)
8. [Development](#development)

---

## Overview

NovaMind is a fully autonomous Windows desktop AI agent written in Python. It operates on three integrated layers:

- **Eyes** — Vision System that captures screen content, performs dual-engine OCR (Tesseract + EasyOCR), detects UI elements via Windows UI Automation (UIA), and describes visual context for LLM reasoning.

- **Brain** — Multi-agent orchestration engine that receives natural language requests, parses them into structured task plans, dispatches subtasks to 12 specialized agents, verifies outputs independently, and handles failure recovery automatically.

- **Hands** — 12 specialized agents that physically operate the computer: mouse/keyboard control, application launching, data manipulation, email management, network operations, code execution, file management, and Windows system control.

### Design Philosophy

- **Zero conditional routing** — All agent dispatch and classification uses O(1) dict lookups or frozenset membership, no if/elif chains
- **Verified execution** — Every task step independently verified by VerifierAgent before acceptance (prevents hallucination)
- **Crash recovery** — All state transitions persisted to SQLite immediately (survives power loss, process crashes)
- **Event-driven observability** — Central EventBus emits every significant action for debugging, auditing, session replay
- **Modular agents** — Each of 12 agents is self-contained, independently testable, and can be extended
- **Persistent memory** — 14-table SQLite system with semantic search, experience consolidation, and skill library

---

## Complete Agent System

NovaMind includes **12 fully functional agents** that handle different domains:

### 1. **ApplicationAgent** (Desktop App Control)
- Launch any Windows application via Windows Search, Run dialog, or subprocess
- Send keyboard input, mouse clicks, and clipboard operations
- Control MS Paint: draw shapes, fill colors, set pen properties, save files
- Window focus/minimize/maximize management
- Application-specific task automation

**Example:** `"Draw a red sports car in MS Paint"` → Agent launches Paint, generates drawing plan, executes via real mouse movements, saves result

### 2. **SystemAgent** (Windows System Control)
- **Process Management:** List, kill, query by PID/name, set priority levels
- **Registry Operations:** Read, write, delete keys and values
- **Windows Services:** Start, stop, pause, query status, enable/disable
- **Scheduled Tasks:** Create, delete, list, trigger execution
- **Firewall Management:** Add/remove/list rules, query status
- **Performance Monitoring:** Real-time CPU, RAM, disk, GPU, network metrics
- **Event Logs:** Query application/system/security event logs
- **Audio Control:** Get/set volume, mute/unmute, list devices, switch output
- **Display Management:** Get/set resolution, refresh rate, brightness
- **Printer Management:** List printers, set default, print files
- **Network Configuration:** List adapters, query/set IP, DNS configuration
- **Power Control:** Sleep, hibernate, restart, shutdown with delay
- **System Notifications:** Display Windows toast alerts
- **Startup Items:** Add/remove programs from autostart

**Example:** `"Show me CPU and RAM usage"` → Returns real-time performance metrics

### 3. **FileAgent** (Complete File System Management)
- **Read/Write/Copy/Move/Delete/Rename** with auto-backup to trash
- **Archive Operations:** Create/extract ZIP, TAR, GZ, BZ2, LZMA
- **File Type Detection:** Magic-byte file identification (not extension-based)
- **Encoding Detection:** Automatic UTF-8/ASCII/Latin-1/UTF-16 handling
- **Binary File Analysis:** Hexdump generation, binary structure inspection
- **Directory Operations:** Tree traversal, recursive listing, watching
- **File Comparison:** Line-by-line diff generation between files
- **Metadata Management:** Query/edit timestamps, permissions, attributes
- **Search Operations:** Regex/glob-based file search
- **Duplicate Finding:** MD5-based duplicate detection
- **Safe Deletion:** All destructive ops backed up to `~/.novamind/trash/` first

**Protected paths:** Never modifies `C:\Windows`, `C:\Program Files`, `/usr/bin`, `/etc`, `/sys`

**Example:** `"Find all Python files in Desktop"` → Returns matching files with sizes and metadata

### 4. **DataAgent** (Multi-Format Data Manipulation)
- **Formats:** CSV, Excel (XLSX/XLS), JSON, SQL (SQLite + any SQLAlchemy DSN), Parquet
- **Safe Formula Evaluation:** Row-level formulas with AST whitelist (no code injection)
- **Data Transformation:** Filtering, sorting, grouping, pivoting, aggregation
- **Schema Inference:** Automatic type detection (int/float/string/datetime)
- **Statistical Analysis:** Mean, median, std dev, min, max, quartiles
- **Data Cleaning:** Null/duplicate removal, whitespace trimming, type coercion
- **Chart Generation:** CSV → matplotlib charts (line, bar, scatter, histograms)
- **ETL Pipelines:** Sequential transformation steps with error handling
- **SQL Execution:** Direct SQL queries with result set handling
- **Data Profiling:** Row/column/type/null count summaries

**Example:** `"Read sales.csv and show revenue by region"` → Parses CSV, groups by region, returns summary

### 5. **NetworkAgent** (Network & Security Scanning)
- **Port Scanning:** Fast multi-threaded scanning of common and custom ports
- **Service Identification:** Banner grabbing and service mapping
- **HTTP Client:** Request with automatic SSL verification, redirect following
- **DNS Operations:** DNS lookups, reverse lookups, MX record queries
- **SSL Certificate Inspection:** Certificate validation, expiry checking
- **WiFi Management:** Windows WiFi enumeration, profile listing (Windows-specific)
- **IP Geolocation:** IP address information lookup
- **Bandwidth Monitoring:** Network adapter statistics, bytes sent/received
- **Traceroute:** Path tracing to remote hosts
- **WebSocket Ping:** WebSocket endpoint connectivity checking

**Service Map:** 25+ known services (FTP, SSH, HTTP, SMTP, MySQL, PostgreSQL, MongoDB, Redis, RDP, VNC, etc.)

**Example:** `"Scan localhost for open ports"` → Returns list of open ports with service names

### 6. **EmailAgent** (Full SMTP/IMAP Automation)
- **Send Emails:** SMTP with plain text, HTML, attachments, CC, BCC
- **Receive Emails:** IMAP with folder browsing, search, filtering
- **Attachments:** Download, attach files, save to disk, MIME handling
- **Email Threading:** Message-ID tracking, in-reply-to chains, conversation grouping
- **OAuth2 Support:** Modern authentication for Gmail, Outlook, etc.
- **Email Flags:** Mark as read/unread, starred, flagged, spam
- **Folder Operations:** Move between folders, create labels, delete messages
- **Draft Support:** Create drafts, auto-save before sending
- **Header Parsing:** Full email header inspection
- **SSL/TLS:** Secure connections with certificate verification

**Supports:** Gmail, Outlook, Yahoo, corporate SMTP/IMAP servers

**Example:** `"Send an email to john@example.com with subject 'Meeting' and attach report.pdf"` → Connects to SMTP, sends with attachment

### 7. **CodeAgent** (Python & JavaScript Intelligence)
- **Code Execution:** Run Python/JavaScript with timeout, memory limit, output capture
- **AST Analysis:** Detect issues, measure complexity, identify anti-patterns
- **Code Formatting:** black, autopep8 integration
- **Refactoring:** Extract functions, rename variables, reduce complexity
- **Git Integration:** Commit, push, pull, diff, log, branch operations
- **Virtual Environments:** Create, activate, manage venv
- **Package Management:** pip install, requirements.txt, version management
- **Static Analysis:** Pylint, flake8, mypy, bandit integration
- **Test Generation:** Generate unit tests, run pytest, report coverage
- **Profiling:** cProfile execution, identify bottlenecks
- **Error Fixing:** Analyze errors, suggest fixes, test solutions

**Safety:** Code runs in subprocess (never eval/exec in main process), with enforced timeouts

**Example:** `"Write a Python script that sorts a list and run it"` → Generates code, executes, returns output

### 8. **BrowserAgent** (Web Automation)
- **URL Navigation:** Open URLs, wait for page load
- **HTML Parsing:** Extract text, find elements, query DOM
- **Form Interaction:** Fill forms, submit, interact with form controls
- **Screenshot Capture:** Page screenshots, visual verification
- **Cookie Management:** Get/set/clear cookies, session persistence
- **Search Integration:** Web search via Google/Bing/DuckDuckGo

*Note: Advanced Playwright/Selenium automation is framework-ready but currently stub*

**Example:** `"Search the web for Python news"` → Opens search engine, extracts results

### 9. **VerifierAgent** (Output Verification)
- **Independent Verification:** Completely separate LLM call after every action
- **Confidence Scoring:** 0.0-1.0 confidence with forced minimum threshold (0.7)
- **Visual Verification:** Screenshot diff for GUI actions
- **Semantic Matching:** Goal satisfaction checking
- **Recovery Suggestion:** Proposes next action if verification fails

**Critical feature:** Prevents hallucinated success from propagating

**Example:** After ApplicationAgent draws, VerifierAgent checks: "Does this look like a red car?" → confidence 0.92

### 10. **ErrorRecoveryAgent** (Automatic Failure Recovery)
- **Strategy Pattern:** Error type → list of recovery strategies
- **Retry Logic:** Progressive retry with modified parameters
- **Automatic Adaptation:** Switches tools/methods on repeated failures
- **Escalation:** After exhausting strategies, escalates to human

**Recovery strategies per error type:**
- `element_not_found` → Try alternative selector, visual location, pyautogui fallback
- `timeout` → Retry with doubled timeout, break into smaller steps, try alternative tool
- `command_failed` → Modify parameters, try alternative command, provide context
- `generic` → Standard retry with exponential backoff

**Example:** If clicking element fails, tries CSS → XPath → text → ARIA → visual → escalates

### 11. **MemoryAgent** (Experience Management)
- **Context Assembly:** Pull relevant episodic + semantic memories for current task
- **Experience Storage:** Persist task outcomes, successes, failures with metadata
- **Semantic Search:** Find similar past experiences using embeddings
- **Memory Consolidation:** Prune old memories, compact learning journal
- **Skill Library:** Store and retrieve successful action sequences
- **Pattern Recognition:** Automatic lesson extraction from multiple successes

**14-table SQLite database** backing all memory operations

**Example:** `"Remember this worked well"` → Stores experience with embedding for future similar tasks

### 12. **PaintAgent** (MS Paint Automation)
- **Shape Drawing:** Lines, rectangles, circles, polygons
- **Color Filling:** Fill buckets, color picker operations
- **Text Input:** Text insertion with font control
- **Canvas Detection:** Automated canvas boundary finding via vision
- **Save Operations:** File save with path specification
- **Drawing Sequencing:** Multi-step drawing from LLM plan

**Example:** `"Fill this shape with blue"` → Locates color picker, sets blue, applies fill

---

## Core Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           NovaMind v3.0 Architecture                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Input: PyQt6 UI / CLI                                                       │
│         │                                                                    │
│         ▼                                                                    │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    BRAIN (Orchestrator)                              │   │
│  │  • Parse natural language → TaskPlan (LLM + O(1) fallback)         │   │
│  │  • Validate state transitions (VALID_TRANSITIONS frozenset)        │   │
│  │  • Dispatch steps to agents (O(1) dict lookup)                     │   │
│  │  • Checkpoint every transition to StateManager (SQLite)            │   │
│  │  • Emit transitions to EventBus (session replay)                   │   │
│  │  • Verify results with VerifierAgent (independent LLM)             │   │
│  │  • Recover from failures (strategy pattern)                        │   │
│  └──────────────────────────┬───────────────────────────────────────────┘   │
│                             │                                                │
│         ┌───────────────────┼────────────────────┐                           │
│         │                   │                    │                           │
│         ▼                   ▼                    ▼                           │
│  ┌─────────────┐  ┌──────────────────┐  ┌──────────────────────┐            │
│  │ EventBus    │  │ StateManager     │  │ ParallelExecutor     │            │
│  │ pub/sub     │  │ SQLite           │  │ asyncio DAG          │            │
│  │ session     │  │ checkpoint       │  │ scatter/gather       │            │
│  │ replay      │  │ crash recovery   │  │ timeout + retry      │            │
│  └─────────────┘  └──────────────────┘  └──────────────────────┘            │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                      12 AGENT LAYER                                  │   │
│  │                                                                       │   │
│  │  ApplicationAgent   SystemAgent      FileAgent       CodeAgent       │   │
│  │  DataAgent          NetworkAgent     EmailAgent      BrowserAgent    │   │
│  │  VerifierAgent      ErrorRecoveryAgent  MemoryAgent   PaintAgent     │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    INFRASTRUCTURE                                    │   │
│  │  Memory System       Security Layer      Vision System               │   │
│  │  (14-table SQLite)   (O(1) blacklist)    (OCR + UIA + screens)       │   │
│  │  LLM Router          Task Parser         Event Bus                   │   │
│  │  (8 providers)       (NLU + fallback)    (observability)             │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────────────────────┐      ┌─────────────────────────────────────┐  │
│  │ PyQt6 Task Window        │      │ Nova Mindscape (GoDot)     │  │
│  │ Real-time status         │      │ Optional task visualization         │  │
│  │ 30 FPS animation         │      │ Cyberpunk aesthetic                 │  │
│  │ System tray integration  │      │                                     │  │
│  └──────────────────────────┘      └─────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Data Flow: User Request to Task Execution

```
User: "Send an email to alice@example.com with subject 'Report' and attach results.csv"
  │
  ▼
TaskParser.parse(request)
  ├── LLM: NLU → structured TaskPlan
  ├── Fallback: O(1) keyword detection if LLM fails
  └── Returns: TaskPlan { type: EMAIL, steps: [...], risk: LOW }
  │
  ▼
Brain.process_request()
  ├── CommandGuard.check(plan)  → SAFE ✓
  ├── EventBus.emit("task_started")
  ├── StateManager.update(PENDING → RUNNING)
  └── _run_task_execution()
      │
      ├─→ Step 1: EmailAgent.send_email()
      │   ├── Connect to SMTP server
      │   ├── Attach results.csv from disk
      │   ├── Set subject, recipient, body
      │   ├── Send message
      │   └── Return: { success: true, message_id: "..." }
      │
      ├─→ VerifierAgent.verify()
      │   ├── Independent LLM call
      │   ├── Check: "Was email sent successfully?"
      │   ├── Confidence: 0.95
      │   └── Return: { satisfied: true, confidence: 0.95 }
      │
      └─→ Brain.finalize()
          ├── StateManager.update(RUNNING → SUCCESS)
          ├── EventBus.emit("task_completed")
          ├── MemoryAgent.store_experience()
          └── UI callback with result
```

---

## Quick Start

### Installation

```bash
# Clone or download NovaMind
cd Novamind

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers (for BrowserAgent)
playwright install chromium
```

### Configuration

```bash
# Create config directory and get API key
python main.py --setup

# Edit ~/.novamind/.env
# Minimum requirement: At least one LLM API key
GROQ_API_KEY=gsk_...           # Free, fast (recommended for start)
```

### Run NovaMind

```bash
python main.py
```

### Example Tasks

```
"Draw a blue sports car in MS Paint and save it to Desktop"
"Send an email to john@example.com with subject 'Meeting' and attach agenda.pdf"
"Show me CPU and RAM usage"
"Read sales.csv and show revenue by product"
"Scan localhost for open ports"
"Search the web for latest Python news"
"Write a Python script that sorts a list and run it"
"List all files in Downloads folder that were modified today"
"Find duplicate files in my Documents folder"
"Connect to database and query last 100 customers"
```

---

## Detailed Capabilities

### Desktop Automation & Application Control
- Launch **any** Windows application (Start menu search, Win+R, executable path)
- Real mouse movements via pyautogui (not event simulation)
- Keyboard input with clipboard support
- MS Paint drawing: shapes, colors, pen properties, canvas management
- Window focus, minimize, maximize, position queries
- Real-time screen monitoring and change detection

### Complete File System Management
- Read/write text with encoding auto-detection
- Binary file inspection and hexdump
- Recursive copy/move/delete with safe trash backup
- Archive creation: ZIP, TAR, GZ, BZ2, LZMA
- Archive extraction: all formats supported
- Magic-byte file type detection (not extension-based)
- Diff generation: line-by-line comparison
- File search: regex and glob patterns
- Duplicate finding: MD5 hashing
- Metadata: query/edit timestamps, permissions, file sizes
- Directory watching: real-time change notifications

### Multi-Format Data Processing
- **CSV:** Read, write, parse with encoding detection
- **Excel:** XLSX/XLS reading and writing
- **JSON:** Parse, transform, validate
- **SQL:** SQLite + any SQLAlchemy-supported database
- **Parquet:** Read/write columnar data
- Safe formula evaluation: AST-whitelisted row-level formulas
- Statistical analysis: mean, median, std dev, quartiles, histograms
- Data transformation: filter, sort, group, pivot, aggregate
- Schema inference: automatic type detection
- Profiling: row/column/type summaries with null counts

### Network & Security Operations
- **Port Scanning:** Multi-threaded with timeout, service identification
- **Service Mapping:** 25+ known services (SSH, HTTP, MySQL, MongoDB, etc.)
- **DNS Operations:** Lookups, reverse lookups, MX records
- **HTTP Requests:** Full SSL verification, redirect following, timeout handling
- **SSL Certificates:** Expiry checking, validity verification
- **WiFi Management:** Windows WiFi profile enumeration
- **IP Information:** Geolocation, ISP lookup
- **Bandwidth Monitoring:** Network adapter stats, bytes sent/received
- **Traceroute:** Path tracing to remote hosts
- **WebSocket:** Endpoint connectivity checking

### Email Automation
- **Send:** SMTP with TLS/SSL, HTML, attachments, CC, BCC
- **Receive:** IMAP with folder browsing, search, filtering
- **Attachments:** Download, save to disk, attachment inspection
- **Threading:** Message-ID chains, in-reply-to relationships
- **OAuth2:** Modern authentication (Gmail, Outlook, Yahoo)
- **Folders:** Move messages, create labels, archive
- **Flags:** Mark read/unread, starred, flagged, spam
- **Drafts:** Create, auto-save, send
- **Headers:** Full header inspection and parsing

### Code Intelligence
- **Write:** Generate Python/JavaScript/TypeScript from descriptions
- **Execute:** Subprocess isolation, timeout (default 30s), output capture
- **Analyse:** AST inspection, complexity metrics, anti-pattern detection
- **Fix:** Error analysis, targeted fixes, test-and-verify
- **Refactor:** Function extraction, variable renaming, complexity reduction
- **Git:** Commit, push, pull, diff, log, branching
- **Virtual Envs:** Create, activate, manage
- **Packages:** pip install, requirements.txt, version management
- **Testing:** Generate tests, run pytest, coverage reporting
- **Static Analysis:** Pylint, flake8, mypy, bandit integration
- **Profiling:** Bottleneck identification via cProfile

### Windows System Control
- **Processes:** List, kill, query by PID/name, set priority
- **Registry:** Read, write, delete keys and values
- **Services:** Start, stop, pause, query, enable/disable
- **Scheduled Tasks:** Create, delete, list, trigger
- **Event Logs:** Query application/system/security events
- **Firewall:** Add/remove/list rules, query status
- **Performance:** Real-time CPU, RAM, disk, GPU, network metrics
- **Audio:** Volume control, device switching, mute/unmute
- **Display:** Resolution, refresh rate, brightness control
- **Printers:** List, set default, print files
- **Network:** IP configuration, DNS settings, adapter enumeration
- **Power:** Sleep, hibernate, restart, shutdown with delay
- **Notifications:** Windows toast alerts
- **Startup Items:** Add/remove autostart programs

### Vision & Screen Analysis
- **Screenshot:** Full screen or specific region/window
- **OCR:** Dual-engine (Tesseract + EasyOCR) with fallback
- **Screen Description:** LLM-powered natural language description
- **Element Detection:** UI element finding via OCR + UIA + template matching
- **Image Comparison:** Structural similarity, change detection
- **Window Management:** Active window title, window enumeration, focus control
- **Template Matching:** OpenCV-based pattern recognition
- **Color Analysis:** Dominant colors, palette extraction

---

## System Components

### Brain (core/brain.py)
**Central orchestrator** implementing state machine with:
- VALID_TRANSITIONS frozenset enforces finite state machine
- Every transition: StateManager (SQLite) → EventBus → UI callback
- O(1) agent dispatch via dict lookup
- Per-step verification and recovery loop
- Automatic retry with incremental backoff

### Task Parser (core/task_parser.py)
**Natural language understanding** with:
- LLM-based parsing (primary path)
- O(1) task-type detection: WORD_TO_TASK_TYPE inverted index
- O(1) risk assessment: priority-ordered frozensets
- Fast-paths for common patterns (drawing, app control)

### Event Bus (core/event_bus.py)
**Pub/sub observability** emitting:
- task_started, task_completed, task_failed, task_retrying
- tool_call_start, tool_call_end, tool_call_error
- agent_handoff, memory_read, memory_write, safety_check events
- Complete session replay: full chronological event log
- Persistent: all events written to SQLite

### State Manager (core/state_manager.py)
**Write-on-every-transition** SQLite checkpointing:
- dag_nodes table: task status, results, dependencies
- Crash recovery: reconstruct DAG from database
- All transitions atomic: in-memory + SQLite + EventBus

### LLM Router (core/llm_router.py)
**Multi-provider failover** supporting:
- Groq (free, fast Llama 3.3 70B)
- Together AI (long context, code)
- OpenRouter (100+ models)
- xAI (Grok)
- Google Gemini (multimodal)
- Hyperbolic, NVIDIA NIM, Cerebras

**Task-type routing:** Different models for different task types

### Memory System (memory/memory_system.py)
**14-table SQLite** with:
- sessions, tasks, task_steps, agent_actions
- memories (episodic + embeddings)
- learning_journal, skills, error_log
- screenshots, llm_calls, user_preferences
- ui_events, system_events, dag_nodes
- Semantic search via sentence-transformers
- WAL mode: crash-safe writes

### Vision System (vision/vision_system.py)
**Screen perception** providing:
- Screenshot capture via pyautogui
- Dual OCR: Tesseract + EasyOCR with auto-fallback
- Windows UI Automation (UIA) element detection
- Image comparison and structural similarity
- Template matching via OpenCV
- Element caching for performance

### Security Layer (security/command_guard.py)
**O(1) access control** with:
- BLACKLIST_EXACT: frozenset exact command blocking
- Protected paths: C:\Windows, /usr/bin, etc (immutable)
- Risk assessment: SAFE → CRITICAL classification
- Frozenset membership tests (no iteration)

### User Interface (ui/task_window.py)
**PyQt6 animated UI** with:
- 30 FPS cyberpunk aesthetics
- Real-time status updates
- Task history sidebar
- Result display and error messages
- System tray integration

---

## Project Structure

```
novamind/
├── main.py                 # Entry point
├── config.py               # Central constants (O(1) lookups)
├── requirements.txt        # Dependencies
├── README.md              # This file
├── SETUP.md               # Installation
│
├── agents/                # 12 Specialized agents
│   ├── application_agent.py    # Desktop app control
│   ├── system_agent.py         # Windows system ops
│   ├── file_agent.py           # Filesystem ops
│   ├── code_agent.py           # Code intelligence
│   ├── data_agent.py           # Data processing (CSV/Excel/SQL/Parquet)
│   ├── network_agent.py        # Network & security
│   ├── email_agent.py          # SMTP/IMAP automation
│   ├── browser_agent.py        # Web automation
│   ├── verifier_agent.py       # Output verification
│   ├── error_recovery_agent.py # Failure recovery
│   ├── memory_agent.py         # Experience management
│   ├── error_handler.py        # Error analysis
│   ├── apps/paint_agent.py     # MS Paint control
│   └── __init__.py
│
├── core/                  # Core orchestration
│   ├── brain.py               # State machine orchestrator
│   ├── task_parser.py         # NLU with O(1) fallback
│   ├── llm_router.py          # Multi-provider LLM routing
│   ├── event_bus.py           # Pub/sub + session replay
│   ├── state_manager.py       # SQLite checkpointing
│   ├── parallel_engine.py     # asyncio DAG executor
│   ├── scheduler.py           # Task scheduling
│   ├── element_finder.py      # UI element detection
│   ├── vision_system.py       # Screen capture + OCR
│   ├── os_executor.py         # Command execution
│   ├── bridge_server.py       # IPC
│   ├── log_manager.py         # Structured logging
│   ├── runtime_paths.py       # Path resolution
│   ├── uia_executor.py        # Windows UI Automation
│   ├── perception.py          # Sensor aggregation
│   ├── tool_result.py         # Tool result dataclass
│   ├── base_agent.py          # Agent base class
│   └── __init__.py
│
├── memory/                # Persistent memory
│   ├── memory_system.py       # 14-table SQLite
│   └── __init__.py
│
├── security/              # Access control
│   ├── command_guard.py       # O(1) blacklist
│   ├── permission_manager.py  # RBAC
│   └── __init__.py
│
├── vision/                # Screen perception
│   ├── vision_system.py       # OCR + element detection
│   ├── screen_analyzer.py     # Screenshot analysis
│   └── __init__.py
│
├── ui/                    # User interface
│   ├── task_window.py         # PyQt6 UI (30 FPS)
│   └── __init__.py
│
├── game/                  # Optional 3D visualization
│   ├── nova_mindscape.py      # Ursina 3D game
│   ├── nova_mindscape_launcher.py
│   ├── texture_gen.py
│   └── assets/
│
├── godot_client/          # Alternative Godot client (optional)
│   ├── Main.tscn
│   ├── NetworkManager.gd
│   ├── Terminal.gd
│   └── project.godot
│
├── tools/                 # Development utilities
│   ├── create_full_audit.py
│   ├── generate_audit.py
│   ├── import_checker.py
│   ├── run_dep_check.py
│   └── setup_godot.py
│
└── tests/                 # Test suite
    ├── test_core.py
    ├── test_focus_chaos.py
    ├── verify_3_fixes.py
    └── test.py
```

---

## Development

### Running Tests

```bash
pytest tests/
```

### Adding a New Agent

1. Create `agents/my_agent.py` inheriting from `BaseAgent`
2. Implement `execute(action: str, params: Dict) -> Dict`
3. Register in Brain's agent dict
4. Add tests

### Configuration

**File:** `config.py` — Central constants with O(1) dict lookups, no hardcoded values

**Environment:** `~/.novamind/.env`
```
GROQ_API_KEY=gsk_...
LOG_LEVEL=INFO
PYAUTOGUI_PAUSE=0.05
```

### Debugging

```python
from core.log_manager import get_logger
logger = get_logger("MyModule")
logger.info("Message")
logger.error("Error", exc_info=True)
```

Session replay:
```python
mem = MemorySystem()
events = mem.get_system_events(session_id="abc123")
```

### Performance Profiling

```bash
python -m cProfile -s cumulative main.py > profile.txt
```

---

## Troubleshooting

### OCR not working
- Falls back to EasyOCR automatically
- For Tesseract: install from https://github.com/UB-Mannheim/tesseract

### LLM Provider Errors
- Check API keys in `~/.novamind/.env`
- Router automatically failsover to next provider
- Check internet connectivity

### Element Not Found
- ApplicationAgent tries: CSS → XPath → text → ARIA → vision → escalates
- All failures logged with recovery suggestions

### Email Connection Issues
- Verify IMAP/SMTP ports (typically 993 for IMAP, 587 for SMTP)
- Check if Gmail requires "Less secure app access" or App Passwords
- Corporate networks may require proxy configuration

---

## Architecture Patterns

### O(1) Routing
No if/elif chains. All dispatch via dict lookup or frozenset:
```python
agent = agents.get(step.agent)        # Dict lookup
error_type_strategies = RECOVERY_STRATEGIES.get(error_type)  # Dict lookup
is_risky = keyword in CRITICAL_KEYWORDS  # frozenset O(1)
```

### State Machine
Every state transition validated against VALID_TRANSITIONS frozenset.

### Verified Execution
Every tool call followed by independent VerifierAgent check.

### Crash Recovery
All state persisted to SQLite immediately.

### Event-Driven Architecture
All significant actions emitted to EventBus for debugging and replay.

---

## License

Apache License 2.0 — See LICENSE file for details.

## Contributing

Contributions welcome! Areas of focus:

- Expanding agent capabilities
- Performance optimizations
- Additional LLM provider support
- Enhanced vision accuracy
- Extended test coverage

## Support

For issues, questions, or suggestions:
1. Check existing GitHub issues
2. Review logs in `~/.novamind/logs/`
3. Enable debug: `LOG_LEVEL=DEBUG`
4. Submit issue with logs and reproduction steps

---

**NovaMind v3.0** — 12 agents, event-driven, crash-safe, verified execution.
