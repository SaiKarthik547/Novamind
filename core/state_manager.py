"""
StateManager — Writes workflow state to SQLite on every transition.
Crash recovery: system can resume from any checkpoint after a restart.
Pattern: LangGraph checkpointing mapped to our SQLite backend.
"""
import json
import logging
import sqlite3
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("StateManager")


class TaskStatus(Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    RETRYING  = "retrying"


@dataclass
class TaskNode:
    id: str
    description: str
    agent_type: str
    tool: str
    args: Dict
    depends_on: List[str]
    expected_output: Dict
    risk_level: int
    timeout: int = 30
    retry_limit: int = 3
    retry_count: int = 0
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[str] = None


class StateManager:
    """
    Writes every task-node transition to SQLite immediately.
    No state lives only in memory — every change survives a crash.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._ensure_table()
        logger.info(f"StateManager ready ({db_path})")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _ensure_table(self) -> None:
        with self._lock:
            conn = self._conn()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dag_nodes (
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
            """)
            conn.commit()
            conn.close()

    def save_session_state(self, session_id: str,
                           dag: List[TaskNode]) -> None:
        with self._lock:
            conn = self._conn()
            conn.executemany(
                """INSERT OR REPLACE INTO dag_nodes
                   (id, session_id, description, agent_type, tool,
                    args, depends_on, status, retry_count, result,
                    error, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    (n.id, session_id, n.description, n.agent_type,
                     n.tool, json.dumps(n.args, default=str),
                     json.dumps(n.depends_on),
                     n.status.value, n.retry_count,
                     json.dumps(n.result, default=str) if n.result else None,
                     n.error, datetime.now().isoformat())
                    for n in dag
                ],
            )
            conn.commit()
            conn.close()

    def update_task(self, task_id: str, session_id: str,
                    status: TaskStatus, result: Any = None,
                    error: str = None, retry_count: int = None) -> None:
        """Write-on-every-transition checkpoint."""
        with self._lock:
            conn = self._conn()
            updates: Dict[str, Any] = {
                "status": status.value,
                "updated_at": datetime.now().isoformat(),
            }
            if result is not None:
                updates["result"] = json.dumps(result, default=str)
            if error is not None:
                updates["error"] = error
            if retry_count is not None:
                updates["retry_count"] = retry_count

            set_clause = ", ".join(f"{k}=?" for k in updates)
            params = list(updates.values()) + [task_id, session_id]
            conn.execute(
                f"UPDATE dag_nodes SET {set_clause} "
                f"WHERE id=? AND session_id=?",
                params,
            )
            conn.commit()
            conn.close()
        logger.debug(f"[StateManager] {task_id} → {status.value}")

    def load_session_state(self, session_id: str) -> List[Dict]:
        """Reconstruct DAG from database for crash recovery."""
        with self._lock:
            conn = self._conn()
            rows = conn.execute(
                "SELECT * FROM dag_nodes WHERE session_id=?",
                (session_id,),
            ).fetchall()
            conn.close()
        return [dict(r) for r in rows]

    def get_all_sessions(self) -> List[str]:
        with self._lock:
            conn = self._conn()
            rows = conn.execute(
                "SELECT DISTINCT session_id FROM dag_nodes "
                "ORDER BY updated_at DESC"
            ).fetchall()
            conn.close()
        return [r["session_id"] for r in rows]
