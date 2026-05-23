import sys
import unittest
from typing import FrozenSet

from core.runtime.syscall_gate import install_import_hook, CapabilityPolicyHook
from core.runtime.exceptions import ImportCapabilityViolation

class TestCapabilityEscape(unittest.TestCase):
    def setUp(self):
        self.basic_hook = CapabilityPolicyHook(frozenset(["compute"]))
        self.network_hook = CapabilityPolicyHook(frozenset(["compute", "network"]))
        self.process_hook = CapabilityPolicyHook(frozenset(["compute", "process_spawn"]))

    def test_bootstrap_allowlist(self):
        self.assertIsNone(self.basic_hook.find_spec("json", None))
        self.assertIsNone(self.basic_hook.find_spec("asyncio", None))
        self.assertIsNone(self.basic_hook.find_spec("sys", None))
        self.assertIsNone(self.basic_hook.find_spec("encodings.utf_8", None))

    def test_application_allowlist(self):
        self.assertIsNone(self.basic_hook.find_spec("core.runtime.worker_sandbox", None))
        self.assertIsNone(self.basic_hook.find_spec("workers.shell_worker", None))

    def test_network_violation(self):
        with self.assertRaises(ImportCapabilityViolation):
            self.basic_hook.find_spec("socket", None)
            
        with self.assertRaises(ImportCapabilityViolation):
            self.basic_hook.find_spec("urllib.request", None)

    def test_network_allowed_with_capability(self):
        self.assertIsNone(self.network_hook.find_spec("socket", None))
        self.assertIsNone(self.network_hook.find_spec("urllib.request", None))

    def test_process_spawn_violation(self):
        with self.assertRaises(ImportCapabilityViolation):
            self.basic_hook.find_spec("subprocess", None)

    def test_process_spawn_allowed_with_capability(self):
        self.assertIsNone(self.process_hook.find_spec("subprocess", None))

if __name__ == "__main__":
    unittest.main()
