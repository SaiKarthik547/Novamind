"""
memory/memory_system.py

14-table SQLite episodic + semantic memory system.
WAL journal mode — crash-safe writes, no full fsync overhead.
Thread-safe via a per-connection threading.Lock.
All branching uses dict dispatch — zero if/elif chains.
"""
import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.foundation.runtime_paths import runtime_path

logger = logging.getLogger("MemorySystem")

DB_PATH = str(runtime_path("memory.db"))

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT UNIQUE NOT NULL,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    task_count  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id       TEXT UNIQUE NOT NULL,
    session_id    TEXT,
    request       TEXT,
    task_type     TEXT,
    risk_level    TEXT,
    status        TEXT DEFAULT 'pending',
    summary       TEXT,
    total_steps   INTEGER DEFAULT 0,
    steps_ok      INTEGER DEFAULT 0,
    steps_fail    INTEGER DEFAULT 0,
    error_summary TEXT,
    started_at    TEXT,
    ended_at      TEXT
);

CREATE TABLE IF NOT EXISTS steps (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT,
    step_number INTEGER,
    description TEXT,
    agent       TEXT,
    action      TEXT,
    parameters  TEXT,
    status      TEXT DEFAULT 'pending',
    output      TEXT,
    error       TEXT,
    retry_count INTEGER DEFAULT 0,
    started_at  TEXT,
    ended_at    TEXT
);

CREATE TABLE IF NOT EXISTS memories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT,
    content     TEXT,
    memory_type TEXT DEFAULT 'episodic',
    importance  REAL DEFAULT 0.5,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS semantic_memories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT,
    value       TEXT,
    category    TEXT,
    created_at  TEXT,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS episodes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task        TEXT,
    task_type   TEXT,
    steps_ok    INTEGER,
    steps_fail  INTEGER,
    success     INTEGER,
    error       TEXT,
    duration    REAL,
    timestamp   TEXT
);

CREATE TABLE IF NOT EXISTS skills (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT,
    description  TEXT,
    usage_count  INTEGER DEFAULT 0,
    success_rate REAL DEFAULT 0.0,
    last_used    TEXT
);

CREATE TABLE IF NOT EXISTS context_windows (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT,
    context     TEXT,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS agent_states (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    agent      TEXT,
    state      TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS tool_results (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    TEXT,
    step_id    INTEGER,
    agent      TEXT,
    action     TEXT,
    parameters TEXT,
    result     TEXT,
    success    INTEGER,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS errors (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    TEXT,
    agent      TEXT,
    action     TEXT,
    error_msg  TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS system_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT,
    data       TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS preferences (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    key        TEXT UNIQUE,
    value      TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS relationships (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_a   TEXT,
    relation   TEXT,
    entity_b   TEXT,
    strength   REAL DEFAULT 1.0,
    created_at TEXT
);
"""


class MemorySystem:
    """
    14-table SQLite-backed episodic + semantic memory.
    Thread-safe: every public method acquires self._lock before touching SQLite.
    All branching uses dict dispatch — zero if/elif chains.
    """

    def __init__(self, db_path: str = DB_PATH):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._session_id = f"session_{int(time.time())}"
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_db()
        self._start_session()
        logger.info(f"MemorySystem ready: {db_path}")

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        import contextlib
        conn = sqlite3.connect(self._db_path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._conn()
            try:
                conn.executescript(SCHEMA_SQL)
                # Verify critical columns exist; CREATE TABLE IF NOT EXISTS doesn't alter existing tables.
                conn.execute("SELECT session_id FROM sessions LIMIT 1")
                conn.close()
            except Exception as e:
                conn.close()
                # Schema mismatch (e.g. stale DB missing session_id column).
                # Nuke the stale DB and rebuild with the current schema.
                logger.warning(f"Schema mismatch ({e}) — rebuilding database at {self._db_path}")
                import time
                try:
                    # Windows file lock delay
                    time.sleep(0.1)
                    if os.path.exists(self._db_path):
                        os.remove(self._db_path)
                    if os.path.exists(self._db_path + "-wal"):
                        os.remove(self._db_path + "-wal")
                    if os.path.exists(self._db_path + "-shm"):
                        os.remove(self._db_path + "-shm")
                except Exception as rem_e:
                    logger.error(f"Failed to delete stale DB: {rem_e}")
                
                new_conn = self._conn()
                try:
                    new_conn.executescript(SCHEMA_SQL)
                finally:
                    new_conn.close()
                logger.info("Database rebuilt with current schema")

    def _start_session(self) -> None:
        with self._lock:
            import contextlib
            with contextlib.closing(self._conn()) as conn:
                with conn:
                    conn.execute(
                        "INSERT OR IGNORE INTO sessions (session_id, started_at) VALUES (?,?)",
                        (self._session_id, datetime.now().isoformat()),
                    )

    def _now(self) -> str:
        return datetime.now().isoformat()

    def _jdump(self, obj: Any, limit: int = 2000) -> str:
        return json.dumps(obj, default=str)[:limit]

    # ── Task lifecycle ────────────────────────────────────────────────────────

    def record_task_start(self, task_id: str, request: str,
                          task_type: str = "", risk_level: str = "",
                          summary: str = "", total_steps: int = 0) -> None:
        with self._lock:
            import contextlib
            with contextlib.closing(self._conn()) as conn:
                with conn:
                    conn.execute(
                        """INSERT OR REPLACE INTO tasks
                           (task_id, session_id, request, task_type, risk_level,
                            status, summary, total_steps, started_at)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (task_id, self._session_id, request[:2000], task_type,
                         risk_level, "running", summary[:1000], total_steps,
                         self._now()),
                    )
                    conn.execute(
                        "UPDATE sessions SET task_count = task_count + 1 WHERE session_id = ?",
                        (self._session_id,),
                    )

    def record_task_end(self, task_id: str, status: str,
                        steps_ok: int = 0, steps_fail: int = 0,
                        error_summary: str = None) -> None:
        with self._lock:
            import contextlib
            with contextlib.closing(self._conn()) as conn:
                with conn:
                    conn.execute(
                        """UPDATE tasks SET status=?, steps_ok=?, steps_fail=?,
                           error_summary=?, ended_at=? WHERE task_id=?""",
                        (status, steps_ok, steps_fail,
                         (error_summary or "")[:1000], self._now(), task_id),
                    )

    def record_step_start(self, task_id: str, step_number: int,
                          description: str, agent: str, action: str,
                          parameters: Dict) -> Optional[int]:
        with self._lock:
            with self._conn() as conn:
                cur = conn.execute(
                    """INSERT INTO steps
                       (task_id, step_number, description, agent, action,
                        parameters, status, started_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (task_id, step_number, description[:500], agent, action,
                     self._jdump(parameters), "running", self._now()),
                )
                return cur.lastrowid

    def record_step_end(self, step_db_id: int, status: str,
                        output: str = "", error: str = "",
                        retry_count: int = 0) -> None:
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """UPDATE steps SET status=?, output=?, error=?,
                       retry_count=?, ended_at=? WHERE id=?""",
                    (status, (output or "")[:3000], (error or "")[:1000],
                     retry_count, self._now(), step_db_id),
                )

    def record_agent_action(self, task_id: str, agent: str, action: str,
                            parameters: Dict, result: Dict,
                            step_id: int = None) -> None:
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO tool_results
                       (task_id, step_id, agent, action, parameters,
                        result, success, created_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (task_id, step_id, agent, action,
                     self._jdump(parameters),
                     self._jdump(result),
                     int(bool(result.get("success", False))),
                     self._now()),
                )

    def log_error(self, error_msg: str, task_id: str = "",
                  agent: str = "", action: str = "",
                  severity: str = "") -> None:
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO errors
                       (task_id, agent, action, error_msg, created_at)
                       VALUES (?,?,?,?,?)""",
                    (task_id, agent, action, (error_msg or "")[:2000],
                     self._now()),
                )

    def store_experience(self, experience: Dict) -> None:
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO episodes
                       (task, task_type, steps_ok, steps_fail, success,
                        error, duration, timestamp)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        str(experience.get("task", ""))[:500],
                        str(experience.get("task_type", "")),
                        int(experience.get("steps_ok", 0)),
                        int(experience.get("steps_fail", 0)),
                        int(bool(experience.get("success", False))),
                        str(experience.get("error", ""))[:500],
                        float(experience.get("duration", 0.0)),
                        str(experience.get("timestamp", self._now())),
                    ),
                )

    def find_similar_experiences(self, query: str,
                                 limit: int = 3) -> List[Dict]:
        """Substring search fallback. Returns up to `limit` relevant past episodes."""
        with self._lock:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT task, task_type, steps_ok, steps_fail,
                              success, error, duration, timestamp
                       FROM episodes
                       WHERE task LIKE ?
                       ORDER BY timestamp DESC LIMIT ?""",
                    (f"%{query[:50]}%", limit),
                ).fetchall()
                return [dict(r) for r in rows]

    def log_system_event(self, event_type: str, data: Any = None,
                         details: str = None, severity: str = "info") -> None:
        """Log a system/infrastructure event. `data` or `details` accepted."""
        _resolve: Dict[bool, Any] = {
            True:  lambda: str(details)[:2000],
            False: lambda: self._jdump(data or {}),
        }
        payload = _resolve[details is not None]()
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO system_events (event_type, data, created_at)
                       VALUES (?,?,?)""",
                    (event_type, payload, self._now()),
                )

    def get_memory_stats(self) -> Dict:
        with self._lock:
            with self._conn() as conn:
                def _q(sql: str) -> int:
                    return conn.execute(sql).fetchone()[0]
                return {
                    "total_memories":      _q("SELECT COUNT(*) FROM memories"),
                    "total_tasks":         _q("SELECT COUNT(*) FROM tasks"),
                    "total_steps":         _q("SELECT COUNT(*) FROM steps"),
                    "total_errors":        _q("SELECT COUNT(*) FROM errors"),
                    "total_tool_results":  _q("SELECT COUNT(*) FROM tool_results"),
                    "total_episodes":      _q("SELECT COUNT(*) FROM episodes"),
                    "total_system_events": _q("SELECT COUNT(*) FROM system_events"),
                    "session_id":          self._session_id,
                    "db_path":             self._db_path,
                }

    # ── Semantic / preference storage ─────────────────────────────────────────

    def set_preference(self, key: str, value: str) -> None:
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO preferences (key, value, updated_at)
                       VALUES (?,?,?)""",
                    (key, value[:2000], self._now()),
                )

    def get_preference(self, key: str, default: str = "") -> str:
        with self._lock:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT value FROM preferences WHERE key=?", (key,)
                ).fetchone()
                _get: Dict[bool, Any] = {
                    True:  lambda: row["value"],
                    False: lambda: default,
                }
                return _get[row is not None]()

    def store_semantic(self, key: str, value: str, category: str = "") -> None:
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO semantic_memories
                       (key, value, category, created_at, updated_at)
                       VALUES (?,?,?,?,?)""",
                    (key, value[:2000], category, self._now(), self._now()),
                )

    def search_semantic(self, query: str, limit: int = 5) -> List[Dict]:
        with self._lock:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT key, value, category, updated_at
                       FROM semantic_memories
                       WHERE key LIKE ? OR value LIKE ?
                       ORDER BY updated_at DESC LIMIT ?""",
                    (f"%{query[:50]}%", f"%{query[:50]}%", limit),
                ).fetchall()
                return [dict(r) for r in rows]

    # ── Context window helpers ────────────────────────────────────────────────

    def save_context(self, task_id: str, context: Dict) -> None:
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO context_windows (task_id, context, created_at)
                       VALUES (?,?,?)""",
                    (task_id, self._jdump(context), self._now()),
                )

    def load_context(self, task_id: str) -> Optional[Dict]:
        with self._lock:
            with self._conn() as conn:
                row = conn.execute(
                    """SELECT context FROM context_windows
                       WHERE task_id=? ORDER BY id DESC LIMIT 1""",
                    (task_id,),
                ).fetchone()
                _parse: Dict[bool, Any] = {True: lambda: json.loads(row["context"])}
                action = _parse.get(row is not None)
                try:
                    return action() if action else None
                except Exception:
                    return None

    # ── Agent state snapshots ─────────────────────────────────────────────────

    def save_agent_state(self, agent: str, state: Dict) -> None:
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO agent_states (agent, state, updated_at)
                       VALUES (?,?,?)""",
                    (agent, self._jdump(state), self._now()),
                )

    # ── Skill registry ────────────────────────────────────────────────────────

    def upsert_skill(self, name: str, description: str,
                     success: bool = True) -> None:
        with self._lock:
            with self._conn() as conn:
                existing = conn.execute(
                    "SELECT id, usage_count, success_rate FROM skills WHERE name=?",
                    (name,),
                ).fetchone()
                _ops: Dict[bool, Any] = {
                    True: lambda: conn.execute(
                        """UPDATE skills SET usage_count=?, success_rate=?,
                           last_used=?, description=? WHERE name=?""",
                        (
                            existing["usage_count"] + 1,
                            (existing["success_rate"] * existing["usage_count"] +
                             int(success)) / (existing["usage_count"] + 1),
                            self._now(), description[:500], name,
                        ),
                    ),
                    False: lambda: conn.execute(
                        """INSERT INTO skills
                           (name, description, usage_count, success_rate, last_used)
                           VALUES (?,?,?,?,?)""",
                        (name, description[:500], 1, float(success), self._now()),
                    ),
                }
                _ops[existing is not None]()

    # ── Session close ─────────────────────────────────────────────────────────

    def end_session(self) -> None:
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    "UPDATE sessions SET ended_at=? WHERE session_id=?",
                    (self._now(), self._session_id),
                )
        logger.info(f"MemorySystem: session {self._session_id} ended")

    def close(self) -> None:
        logger.info("MemorySystem closed.")

    @property
    def db_path(self) -> str:
        return self._db_path
