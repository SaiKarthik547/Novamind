import pytest
import shutil
import json
from pathlib import Path
from core.replay.event_recorder import EventRecorder, MAX_SEGMENT_EVENTS
from core.replay.replay_engine import ReplayEngine, ReplayMode

@pytest.fixture
def session_dir(tmp_path):
    dir_path = tmp_path / "test_session_seg"
    yield dir_path
    if dir_path.exists():
        shutil.rmtree(dir_path)

@pytest.mark.asyncio
async def test_wal_segmentation_on_commit(session_dir):
    recorder = EventRecorder(log_dir=str(session_dir.parent), session_id="test_seg")
    actual_session_dir = recorder.session_dir
    await recorder.start()
    
    recorder.log_event("TEST", "core", "info", {"v": 1})
    recorder.log_event("SNAPSHOT_COMMIT", "core", "info", {"snapshot_id": "test_snap"})
    recorder.log_event("TEST", "core", "info", {"v": 2})
    await recorder.stop()
    
    # Verify segments created
    assert (actual_session_dir / "00000.jsonl").exists()
    assert (actual_session_dir / "00001.jsonl").exists()
    
    # Verify manifest
    manifest_path = actual_session_dir / "manifest.json"
    assert manifest_path.exists()
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
        assert manifest["segment_count"] == 2
        assert manifest["checkpoint_segments"] == [0]

    # Replay across segments
    engine = ReplayEngine(mode=ReplayMode.STRICT)
    class MockBus:
        def publish(self, e): pass
    
    success = await engine.execute_recovery(None, actual_session_dir, MockBus())
    assert success is True
    assert engine.cursor.events_processed == 3
    assert engine.cursor.segment_id == "00001"
