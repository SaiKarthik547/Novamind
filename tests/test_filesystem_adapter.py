import unittest
import os
import tempfile
from core.adapters.filesystem_adapter import FilesystemAdapter
from core.execution.execution_intent import ExecutionIntent, VerificationMode, RollbackMode

class TestFilesystemAdapter(unittest.TestCase):
    def setUp(self):
        self.adapter = FilesystemAdapter()
        self.adapter.initialize()
        self.adapter.attach()
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_write_and_read(self):
        test_file = os.path.join(self.temp_dir, "test.txt")
        
        # Write
        write_intent = ExecutionIntent(
            adapter="filesystem",
            operation="write",
            idempotent=False,
            verification_mode=VerificationMode.STRUCTURAL,
            rollback_strategy=RollbackMode.NO_ROLLBACK,
            capability_scope={},
            payload={"path": test_file, "content": "hello filesystem"}
        )
        write_result = self.adapter.execute(write_intent)
        self.assertTrue(write_result["success"])
        
        # Read
        read_intent = ExecutionIntent(
            adapter="filesystem",
            operation="read",
            idempotent=True,
            verification_mode=VerificationMode.STRUCTURAL,
            rollback_strategy=RollbackMode.NO_ROLLBACK,
            capability_scope={},
            payload={"path": test_file}
        )
        read_result = self.adapter.execute(read_intent)
        self.assertTrue(read_result["success"])
        self.assertEqual(read_result["content"], "hello filesystem")

    def test_mkdir_and_delete(self):
        test_dir = os.path.join(self.temp_dir, "new_dir")
        
        # Mkdir
        mkdir_intent = ExecutionIntent(
            adapter="filesystem",
            operation="mkdir",
            idempotent=True,
            verification_mode=VerificationMode.STRUCTURAL,
            rollback_strategy=RollbackMode.NO_ROLLBACK,
            capability_scope={},
            payload={"path": test_dir}
        )
        mkdir_result = self.adapter.execute(mkdir_intent)
        self.assertTrue(mkdir_result["success"])
        self.assertTrue(os.path.isdir(test_dir))
        
        # Delete
        delete_intent = ExecutionIntent(
            adapter="filesystem",
            operation="delete",
            idempotent=True,
            verification_mode=VerificationMode.STRUCTURAL,
            rollback_strategy=RollbackMode.NO_ROLLBACK,
            capability_scope={},
            payload={"path": test_dir}
        )
        delete_result = self.adapter.execute(delete_intent)
        self.assertTrue(delete_result["success"])
        self.assertFalse(os.path.exists(test_dir))

if __name__ == '__main__':
    unittest.main()
