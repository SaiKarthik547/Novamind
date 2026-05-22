import subprocess
from workers.worker_base import WorkerBase

class ShellWorker(WorkerBase):
    """
    Isolated worker for executing shell commands.
    In a hardened setup, this process would be launched under a restricted Job Object
    and stripped token, limiting its blast radius.
    """
    def handle_request(self, payload: dict) -> dict:
        command = payload.get("command")
        cwd = payload.get("cwd")
        timeout = payload.get("timeout", 60)
        
        if not command:
            raise ValueError("No command provided")
            
        # Actual execution
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            return {
                "stdout": stdout,
                "stderr": stderr,
                "returncode": proc.returncode
            }
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            raise TimeoutError(f"Command timed out after {timeout}s")

if __name__ == "__main__":
    worker = ShellWorker()
    worker.run()
