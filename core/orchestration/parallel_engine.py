"""
ParallelExecutionEngine — asyncio DAG runner.
Scatter-gather pattern from LangGraph production architecture.
Independent tasks run simultaneously; newly unblocked nodes launch
as dependencies complete. State written on every transition.
"""
import asyncio
import logging
import uuid
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger("ParallelEngine")


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
    risk_level: int = 0
    timeout: int = 30
    retry_limit: int = 3
    retry_count: int = 0
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class ParallelExecutionEngine:
    """
    The core parallel runtime.
    Receives a DAG of TaskNodes; runs all nodes with satisfied
    dependencies simultaneously using asyncio.gather().
    This is what makes complex tasks fast — all independent work
    runs at the same time.
    """

    def __init__(self, agents: Dict, event_bus, state_manager,
                 session_id: str = None, gui_lock: threading.Lock = None,
                 gui_agents: Set[str] = None):
        self.agents = agents
        self.event_bus = event_bus
        self.state_manager = state_manager
        self.session_id = session_id or str(uuid.uuid4())
        self.gui_lock = gui_lock or threading.Lock()
        self.gui_agents = gui_agents or set()
        self._running_tasks: Dict[str, asyncio.Task] = {}

    async def execute_dag(self, task_dag: List[TaskNode]) -> Dict[str, Any]:
        """
        Execute a DAG of tasks with full parallel dispatch.
        Returns dict with completed/failed sets and per-task results.

        L4-B: CONCURRENCY RULE \u2014 non-commutative intents MUST be serialized.
        Only intents with commutative=True may run in parallel.
        See core/execution/kernel_facade.py for the enforcement point.
        TaskNodes that touch the same resource (GUI, filesystem path, process tree)
        must declare exclusive_resource_locks and be serialized by the kernel.
        """
        task_map: Dict[str, TaskNode] = {t.id: t for t in task_dag}
        results: Dict[str, Any] = {}
        completed: Set[str] = set()
        failed: Set[str] = set()

        self.state_manager.save_session_state(self.session_id, task_dag)

        await self.event_bus.emit("session_started", {
            "session_id": self.session_id,
            "total_nodes": len(task_dag),
        })

        while len(completed) + len(failed) < len(task_dag):
            ready = [
                t for t in task_dag
                if t.status == TaskStatus.PENDING
                and all(dep in completed for dep in t.depends_on)
                and t.id not in self._running_tasks
            ]

            if ready:
                new_tasks = {
                    t.id: asyncio.create_task(self._run_node(t, task_map))
                    for t in ready
                }
                self._running_tasks.update(new_tasks)
                for t in ready:
                    t.status = TaskStatus.RUNNING
                    t.started_at = datetime.now().isoformat()
                    self.state_manager.update_task(
                        t.id, self.session_id, TaskStatus.RUNNING
                    )
                    await self.event_bus.emit("task_started", {
                        "task_id": t.id,
                        "agent": t.agent_type,
                        "tool": t.tool,
                        "session_id": self.session_id,
                    })

            if not self._running_tasks:
                break

            done, _ = await asyncio.wait(
                self._running_tasks.values(),
                return_when=asyncio.FIRST_COMPLETED,
            )

            for finished in done:
                task_id = next(
                    tid for tid, t in self._running_tasks.items()
                    if t is finished
                )
                del self._running_tasks[task_id]
                node = task_map[task_id]

                try:
                    result = finished.result()
                    node.result = result
                    node.status = TaskStatus.COMPLETED
                    node.completed_at = datetime.now().isoformat()
                    completed.add(task_id)
                    results[task_id] = result

                    self.state_manager.update_task(
                        task_id, self.session_id,
                        TaskStatus.COMPLETED, result=result
                    )
                    await self.event_bus.emit("task_completed", {
                        "task_id": task_id,
                        "session_id": self.session_id,
                        "result_summary": str(result)[:200],
                    })

                except Exception as exc:
                    node.error = str(exc)

                    if node.retry_count < node.retry_limit:
                        node.retry_count += 1
                        node.status = TaskStatus.PENDING
                        self.state_manager.update_task(
                            task_id, self.session_id,
                            TaskStatus.RETRYING,
                            error=str(exc),
                            retry_count=node.retry_count,
                        )
                        await self.event_bus.emit("task_retrying", {
                            "task_id": task_id,
                            "error": str(exc),
                            "attempt": node.retry_count,
                            "session_id": self.session_id,
                        })
                        logger.warning(
                            f"[Engine] {task_id} retry "
                            f"{node.retry_count}/{node.retry_limit}: {exc}"
                        )
                    else:
                        node.status = TaskStatus.FAILED
                        failed.add(task_id)
                        self.state_manager.update_task(
                            task_id, self.session_id,
                            TaskStatus.FAILED, error=str(exc)
                        )
                        await self.event_bus.emit("task_failed", {
                            "task_id": task_id,
                            "error": str(exc),
                            "session_id": self.session_id,
                        })
                        for dep_node in task_dag:
                            if (task_id in dep_node.depends_on
                                    and dep_node.status == TaskStatus.PENDING):
                                dep_node.status = TaskStatus.FAILED
                                failed.add(dep_node.id)
                                self.state_manager.update_task(
                                    dep_node.id, self.session_id,
                                    TaskStatus.FAILED,
                                    error=f"Dependency {task_id} failed",
                                )

        await self.event_bus.emit("session_ended", {
            "session_id": self.session_id,
            "completed": len(completed),
            "failed": len(failed),
        })

        return {
            "session_id": self.session_id,
            "completed": list(completed),
            "failed": list(failed),
            "results": results,
        }

    async def _run_node(self, node: TaskNode,
                        task_map: Dict[str, TaskNode]) -> Any:
        agent = self.agents.get(node.agent_type)
        if agent is None:
            raise ValueError(f"No agent of type: '{node.agent_type}'. "
                             f"Available: {list(self.agents)}")

        await self.event_bus.emit("tool_call_start", {
            "task_id": node.id,
            "agent": node.agent_type,
            "tool": node.tool,
            "args": node.args,
        })

        try:
            result = await asyncio.wait_for(
                self._execute_agent(agent, node, self.gui_lock, self.gui_agents),
                timeout=node.timeout,
            )
            await self.event_bus.emit("tool_call_end", {
                "task_id": node.id,
                "agent": node.agent_type,
                "tool": node.tool,
                "success": True,
            })
            return result

        except asyncio.TimeoutError:
            err = f"Task {node.id} timed out after {node.timeout}s"
            await self.event_bus.emit("tool_call_error", {
                "task_id": node.id,
                "error": err,
            })
            raise TimeoutError(err)

        except Exception as exc:
            await self.event_bus.emit("tool_call_error", {
                "task_id": node.id,
                "error": str(exc),
            })
            raise

    @staticmethod
    async def _execute_agent(agent, node: TaskNode, gui_lock: threading.Lock,
                             gui_agents: Set[str]) -> Any:
        """
        Run agent.execute() in a thread executor so blocking agents
        don't stall the event loop. Serialises GUI-touching agents via gui_lock.
        """
        def _guarded_exec():
            if node.agent_type in gui_agents:
                with gui_lock:
                    return agent.execute(node.tool, node.args)
            return agent.execute(node.tool, node.args)

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _guarded_exec)
