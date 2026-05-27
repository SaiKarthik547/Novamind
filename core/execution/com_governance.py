"""
core/execution/com_governance.py

Phase 15A.5: COM Apartment Governance
Ensures UIAutomation and COM executions are explicitly bound to correctly 
initialized STA (Single-Threaded Apartment) threads.
Prevents silent freezes and cross-thread COM marshaling crashes.
"""

import threading
import logging
import queue
import time
from typing import Callable, Any, Dict
from dataclasses import dataclass

logger = logging.getLogger("COMGovernance")

@dataclass
class COMTask:
    func: Callable
    args: tuple
    kwargs: dict
    result_event: threading.Event
    result: Any = None
    error: Exception = None

class COMApartmentExecutor:
    """
    Maintains a strictly isolated thread initialized for STA COM execution.
    All Lane 1 (UIA) and Lane 4 (COM) intents MUST be dispatched here.
    """
    _instance = None
    _singleton_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> 'COMApartmentExecutor':
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self._task_queue = queue.Queue()
        self._running = False
        self._sta_thread = None
        self._lock = threading.RLock()

    def start(self):
        with self._lock:
            if not self._running:
                self._running = True
                self._sta_thread = threading.Thread(
                    target=self._sta_worker_loop, 
                    daemon=True, 
                    name="STA_COM_Worker"
                )
                self._sta_thread.start()

    def stop(self):
        with self._lock:
            self._running = False
            self._task_queue.put(None)  # Sentinel
        if self._sta_thread:
            self._sta_thread.join(timeout=3.0)

    def execute_in_apartment(self, func: Callable, *args, timeout: float = 30.0, **kwargs) -> Any:
        """
        Submits a callable to the STA thread. Blocks until completion or timeout.
        """
        task = COMTask(
            func=func,
            args=args,
            kwargs=kwargs,
            result_event=threading.Event()
        )
        
        self._task_queue.put(task)
        
        if not task.result_event.wait(timeout=timeout):
            raise TimeoutError(f"COM execution for {func.__name__} timed out after {timeout}s.")
            
        if task.error:
            raise task.error
            
        return task.result

    def _sta_worker_loop(self):
        """
        The isolated STA thread. Initializes COM exactly once for this thread's lifetime.
        """
        try:
            import pythoncom
            # COINIT_APARTMENTTHREADED (2) enforces STA, which is mandatory for most UIAutomation calls.
            pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
            logger.info("[COMGovernance] STA Worker Thread initialized successfully.")
        except ImportError:
            logger.warning("[COMGovernance] pythoncom not available. COM execution will fail.")
            pythoncom = None
        except Exception as e:
            logger.error(f"[COMGovernance] CoInitializeEx failed: {e}")
            pythoncom = None

        while self._running:
            try:
                task = self._task_queue.get(timeout=0.1)
                if task is None: # Sentinel
                    break
                    
                try:
                    task.result = task.func(*task.args, **task.kwargs)
                except Exception as e:
                    task.error = e
                finally:
                    task.result_event.set()
                    self._task_queue.task_done()
                    
            except queue.Empty:
                # Pump COM messages to prevent deadlocks in STA if objects are expecting it
                if pythoncom:
                    pythoncom.PumpWaitingMessages()
                continue
            except Exception as loop_e:
                logger.error(f"[COMGovernance] Loop error: {loop_e}")

        if pythoncom:
            pythoncom.CoUninitialize()
            logger.info("[COMGovernance] STA Worker Thread uninitialized.")
