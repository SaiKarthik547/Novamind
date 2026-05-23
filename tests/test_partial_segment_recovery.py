import pytest
import shutil
import json
from pathlib import Path
from core.replay.event_recorder import EventRecorder
from core.replay.replay_engine import ReplayEngine, ReplayMode

@pytest.fixture
def session_dir(tmp_path):
    dir_path = tmp_path / "test_session_trunc"
    yield dir_path
    if dir_path.exists():
        shutil.rmtree(dir_path)

@pytest.mark.asyncio
async def test_partial_segment_recovery(session_dir):
    recorder = EventRecorder(log_dir=str(session_dir.parent), session_id="test_trunc")
    actual_session_dir = recorder.session_dir
    await recorder.start()
    
    recorder.log_event("TEST1", "core", "info", {"v": 1})
    recorder.log_event("TEST2", "core", "info", {"v": 2})
    await recorder.stop()
    
    segment_file = actual_session_dir / "00000.jsonl"
    with open(segment_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    # Truncate the second line to simulate power loss
    lines[1] = lines[1][:10] # definitely invalid JSON
    
    with open(segment_file, "w", encoding="utf-8") as f:
        f.writelines(lines)
        
    # STRICT mode should fail immediately on corrupt JSON
    engine = ReplayEngine(mode=ReplayMode.STRICT)
    class MockBus:
        def publish(self, e): pass
    
    success = await engine.execute_recovery(None, actual_session_dir, MockBus())
    assert success is False
    
    # SALVAGE mode should recover the first event perfectly and stop safely
    engine_salvage = ReplayEngine(mode=ReplayMode.SALVAGE)
    success_salvage = await engine_salvage.execute_recovery(None, actual_session_dir, MockBus())
    assert success_salvage is True
    assert engine_salvage.cursor.events_processed == 1
    
    # DIAGNOSTIC mode will try to skip the bad line, but because there are no more lines
    # it will just report 1 event processed, but it shouldn't raise exception.
    engine_diag = ReplayEngine(mode=ReplayMode.DIAGNOSTIC)
    success_diag = await engine_diag.execute_recovery(None, actual_session_dir, MockBus())
    assert success_diag is True
    assert engine_diag.cursor.events_processed == 1
