import sys
import unittest
import time
import subprocess
import os

from core.runtime.worker_sandbox import WorkerSandbox, JobAssignmentError
from core.runtime.exceptions import CapabilityViolation

class TestJobObjectEnforcement(unittest.TestCase):
    @unittest.skipIf(sys.platform != "win32", "Job Objects are Windows only")
    def test_job_assignment_success(self):
        sandbox = WorkerSandbox("test_success", profile_name="compute")
        
        # Start a dummy process that stays alive
        proc = subprocess.Popen(["python", "-c", "import time; time.sleep(10)"])
        
        try:
            # Should assign successfully
            sandbox.assign_process(proc.pid)
            
            # The process should be alive
            self.assertIsNone(proc.poll())
        finally:
            sandbox.close() # OS should kill it instantly
            
            # Give OS a moment to kill it
            time.sleep(0.5)
            # Proc should be dead
            self.assertIsNotNone(proc.poll())

    @unittest.skipIf(sys.platform != "win32", "Job Objects are Windows only")
    def test_job_assignment_dead_process(self):
        sandbox = WorkerSandbox("test_dead", profile_name="compute")
        
        # Start a process that exits immediately
        proc = subprocess.Popen(["python", "-c", "pass"])
        proc.wait(timeout=5.0)
        
        # Try to assign a dead PID. It should fail or be a no-op that doesn't crash the supervisor.
        # Often OpenProcess fails with ERROR_INVALID_PARAMETER (87) if it's completely dead.
        try:
            sandbox.assign_process(proc.pid)
        except JobAssignmentError as e:
            # It's okay if it fails with JobAssignmentError because the process is dead
            pass
        finally:
            sandbox.close()

if __name__ == "__main__":
    unittest.main()
