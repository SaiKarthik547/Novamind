import pytest
import os
import shutil
from pathlib import Path
from core.replay.event_recorder import EventRecorder
from core.replay.replay_engine import ReplayEngine, ReplayMode
import asyncio

@pytest.fixture
def session_dir(tmp_path):
    dir_path = tmp_path / "test_session"
    yield dir_path
    if dir_path.exists():
        shutil.rmtree(dir_path)

@pytest.mark.asyncio
async def test_wal_hash_chaining(session_dir):
    recorder = EventRecorder(log_dir=str(session_dir.parent), session_id="test_hash")
    actual_session_dir = recorder.session_dir
    await recorder.start()
    
    recorder.log_event("TEST", "core", "info", {"k": 1})
    recorder.log_event("TEST", "core", "info", {"k": 2})
    await recorder.stop()
    
    # Verify replay succeeds in strict mode
    engine = ReplayEngine(mode=ReplayMode.STRICT)
    
    # Mock EventBus
    class MockBus:
        def publish(self, e): pass
        
    success = await engine.execute_recovery(None, actual_session_dir, MockBus())
    assert success is True
    
    # Now intentionally corrupt the second event
    segment_file = actual_session_dir / "00000.jsonl"
    with open(segment_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    import json
    ev2 = json.loads(lines[1])
    ev2["payload"]["k"] = 999  # tampering
    lines[1] = json.dumps(ev2) + "\n"
    
    with open(segment_file, "w", encoding="utf-8") as f:
        f.writelines(lines)
        
    # Strictly reject forgery
    engine2 = ReplayEngine(mode=ReplayMode.STRICT)
    success = await engine2.execute_recovery(None, actual_session_dir, MockBus())
    assert success is False
    
    # Salvage should recover the first event and stop cleanly
    engine_salvage = ReplayEngine(mode=ReplayMode.SALVAGE)
    success = await engine_salvage.execute_recovery(None, actual_session_dir, MockBus())
    assert success is True
    assert engine_salvage.cursor.events_processed == 1  # Only 1 valid event processed
