import pytest
from core.syscall_gate import SyscallGate, CapabilityViolation

class MockAgentWithSubprocess:
    def __init__(self):
        import subprocess
        self.sp = subprocess

def test_syscall_gate_detects_subprocess():
    # Write a mock agent module to disk to test import blocking
    with open("mock_agent_bad.py", "w") as f:
        f.write("import subprocess\n")
        f.write("class BadAgent:\n")
        f.write("    pass\n")
        
    try:
        import mock_agent_bad
        with pytest.raises(CapabilityViolation):
            SyscallGate.validate_agent_capabilities("mock_agent_bad")
    finally:
        import os
        if os.path.exists("mock_agent_bad.py"):
            os.remove("mock_agent_bad.py")

def test_syscall_gate_allows_safe_agent():
    with open("mock_agent_good.py", "w") as f:
        f.write("import json\n")
        f.write("class GoodAgent:\n")
        f.write("    pass\n")
        
    try:
        import mock_agent_good
        # Should not raise
        SyscallGate.validate_agent_capabilities("mock_agent_good")
    finally:
        import os
        if os.path.exists("mock_agent_good.py"):
            os.remove("mock_agent_good.py")
