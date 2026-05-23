import pytest
import shutil
import json
from pathlib import Path
from core.replay.replay_engine import ReplayEngine, ReplayMode

@pytest.fixture
def legacy_session_dir(tmp_path):
    dir_path = tmp_path / "test_session_legacy"
    dir_path.mkdir(parents=True, exist_ok=True)
    
    # Write a flat JSONL file with NO previous_hash
    log_file = dir_path / "00000.jsonl"
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(json.dumps({"event_type": "LEGACY_1", "payload": {"a": 1}}) + "\n")
        f.write(json.dumps({"event_type": "LEGACY_2", "payload": {"a": 2}}) + "\n")
        
    yield dir_path
    if dir_path.exists():
        shutil.rmtree(dir_path)

@pytest.mark.asyncio
async def test_legacy_wal_strict_rejection(legacy_session_dir):
    engine = ReplayEngine(mode=ReplayMode.STRICT)
    class MockBus:
        def publish(self, e): pass
        
    # Should raise ValueError because it lacks hash chaining
    success = await engine.execute_recovery(None, legacy_session_dir, MockBus())
    assert success is False

@pytest.mark.asyncio
async def test_legacy_wal_diagnostic_fallback(legacy_session_dir):
    engine = ReplayEngine(mode=ReplayMode.DIAGNOSTIC)
    class MockBus:
        def publish(self, e): pass
        
    success = await engine.execute_recovery(None, legacy_session_dir, MockBus())
    assert success is True
    assert engine.cursor.events_processed == 2
    assert engine._legacy_fallback_active is True

@pytest.mark.asyncio
async def test_legacy_wal_salvage_fallback(legacy_session_dir):
    engine = ReplayEngine(mode=ReplayMode.SALVAGE)
    class MockBus:
        def publish(self, e): pass
        
    success = await engine.execute_recovery(None, legacy_session_dir, MockBus())
    assert success is True
    assert engine.cursor.events_processed == 2
    assert engine._legacy_fallback_active is True
