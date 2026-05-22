import pytest
import sys
import psutil
from core.os_utils.windows_job_objects import WindowsJobObject

@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Objects require Windows")
def test_job_object_assignment():
    import subprocess
    proc = subprocess.Popen(["ping", "-n", "10", "127.0.0.1"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    job = WindowsJobObject()
    job.assign_process(proc.pid)
    
    # Verify process is running
    assert proc.poll() is None
    
    # Closing the job object handle should terminate the process due to KILL_ON_JOB_CLOSE
    job.close()
    
    # Wait for OS to reap
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
        
    # Popen.poll() might still return None if python hasn't reaped, so check psutil
    try:
        p = psutil.Process(proc.pid)
        assert not p.is_running() or p.status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        pass # Expected
