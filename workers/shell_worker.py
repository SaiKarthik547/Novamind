"""
workers/shell_worker.py
L4-C: ShellWorker with process tree tracking.

All spawned processes are registered in _registered_pids before exec
and deregistered in the finally block. shell=False enforced for security.
The kernel must be able to audit and terminate any process in this tree.
"""
import shlex
import subprocess
import logging
from workers.worker_base import WorkerBase

logger = logging.getLogger("ShellWorker")


class ShellWorker(WorkerBase):
    """
    Isolated worker for executing shell commands.
    In a hardened setup, this process would be launched under a restricted Job Object
    and stripped token, limiting its blast radius.

    L4-C: process_tree_tracking_required = True
    All spawned PIDs are registered before exec and deregistered on cleanup.
    shell=False enforced: prevents shell injection via command string manipulation.
    """

    # L4-C: Kernel must be able to enumerate and terminate all child processes
    process_tree_tracking_required: bool = True
    _registered_pids: set = set()

    def handle_request(self, payload: dict) -> dict:
        command = payload.get("command")
        cwd = payload.get("cwd")
        timeout = payload.get("timeout", 60)

        if not command:
            raise ValueError("No command provided")

        # L4-C: Normalize command \u2014 accept str or list
        # shell=False required: shell=True bypasses Job Object containment on Windows
        if isinstance(command, str):
            cmd_list = shlex.split(command)
        elif isinstance(command, list):
            cmd_list = command
        else:
            raise ValueError(f"Command must be str or list, got {type(command)}")

        proc = subprocess.Popen(
            cmd_list,
            shell=False,   # L4-C: NEVER shell=True \u2014 breaks Job Object containment
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # L4-C: Register PID for kernel process tree tracking
        ShellWorker._registered_pids.add(proc.pid)
        logger.info(f"[ShellWorker] Spawned PID {proc.pid} | cmd={cmd_list[0]!r}")

        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            logger.info(f"[ShellWorker] PID {proc.pid} exited rc={proc.returncode}")
            return {
                "stdout": stdout,
                "stderr": stderr,
                "returncode": proc.returncode,
                "pid": proc.pid,
            }
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            logger.error(f"[ShellWorker] PID {proc.pid} timed out after {timeout}s \u2014 killed")
            raise TimeoutError(f"Command timed out after {timeout}s")
        finally:
            # L4-C: Always deregister PID, even on crash
            ShellWorker._registered_pids.discard(proc.pid)


if __name__ == "__main__":
    worker = ShellWorker()
    worker.run()
