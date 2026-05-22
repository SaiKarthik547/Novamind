import asyncio
import uuid
import logging
from typing import Dict, Any, Optional, Callable, Awaitable
from datetime import datetime

logger = logging.getLogger(__name__)

class TaskState:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

class Task:
    def __init__(self, name: str, coroutine_func: Callable[..., Awaitable[Any]], *args, **kwargs):
        self.task_id = str(uuid.uuid4())
        self.name = name
        self.state = TaskState.PENDING
        self.created_at = datetime.now()
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.result: Any = None
        self.error: Optional[Exception] = None
        
        self._coroutine_func = coroutine_func
        self._args = args
        self._kwargs = kwargs
        self._asyncio_task: Optional[asyncio.Task] = None

    async def execute(self):
        self.state = TaskState.RUNNING
        self.started_at = datetime.now()
        logger.info(f"Task started: [{self.name}] ({self.task_id})")
        
        try:
            self.result = await self._coroutine_func(*self._args, **self._kwargs)
            self.state = TaskState.COMPLETED
            logger.info(f"Task completed: [{self.name}] ({self.task_id})")
        except asyncio.CancelledError:
            self.state = TaskState.CANCELLED
            logger.warning(f"Task cancelled: [{self.name}] ({self.task_id})")
            raise
        except Exception as e:
            self.state = TaskState.FAILED
            self.error = e
            logger.error(f"Task failed: [{self.name}] ({self.task_id}) - {e}")
        finally:
            self.completed_at = datetime.now()

class TaskManager:
    def __init__(self):
        self.tasks: Dict[str, Task] = {}
        self._queue: asyncio.Queue[Task] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self.is_running = False

    def start(self):
        if not self.is_running:
            self.is_running = True
            self._worker_task = asyncio.create_task(self._worker_loop())
            logger.info("TaskManager started")

    async def stop(self):
        self.is_running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("TaskManager stopped")

    def submit(self, name: str, coroutine_func: Callable[..., Awaitable[Any]], *args, **kwargs) -> str:
        task = Task(name, coroutine_func, *args, **kwargs)
        self.tasks[task.task_id] = task
        self._queue.put_nowait(task)
        logger.debug(f"Task queued: [{name}] ({task.task_id})")
        return task.task_id

    def get_task(self, task_id: str) -> Optional[Task]:
        return self.tasks.get(task_id)

    def cancel_task(self, task_id: str) -> bool:
        task = self.tasks.get(task_id)
        if task and task.state in [TaskState.PENDING, TaskState.RUNNING]:
            if task._asyncio_task:
                task._asyncio_task.cancel()
            task.state = TaskState.CANCELLED
            return True
        return False

    async def _worker_loop(self):
        while self.is_running:
            try:
                task = await self._queue.get()
                if task.state == TaskState.CANCELLED:
                    self._queue.task_done()
                    continue
                    
                # We could run tasks concurrently by using create_task without awaiting directly here,
                # but for an AI orchestrator, sequential or controlled concurrency is usually better.
                # Let's run them as attached asyncio tasks so they can be cancelled.
                task._asyncio_task = asyncio.create_task(task.execute())
                await task._asyncio_task
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"TaskManager worker error: {e}")
