import pytest
import time
import asyncio
from unittest.mock import MagicMock

from core.replay.divergence_analyzer import DivergenceAnalyzer
from core.orchestration.kernel_supervisor import KernelSupervisor

@pytest.fixture
def mock_event_bus():
    return MagicMock()

@pytest.fixture
def mock_recorder():
    return MagicMock()

def test_split_brain_detection(mock_event_bus, mock_recorder):
    """
    Simulates Godot having ghost tasks that Python doesn't know about.
    Asserts DivergenceAnalyzer measures the drop in health accurately.
    """
    analyzer = DivergenceAnalyzer()
    
    python_state = {"active_tasks": ["task_A", "task_B"]}
    godot_state = {"active_tasks": ["task_A", "task_B", "task_GHOST"]}
    
    score = analyzer.compute_divergence(python_state, godot_state)
    
    # 1.0 - (0.4 * (1 / 3)) = ~0.866
    assert score < 1.0
    assert score < 0.95  # Qualifies as degraded health

def test_supervisor_degraded_transition(mock_event_bus, mock_recorder):
    """
    Simulates the auditor reporting a divergence violation to the supervisor.
    Asserts the supervisor formally transitions to DEGRADED and issues STATE_DIVERGENCE.
    """
    from core.bootstrap.runtime_lifecycle import RuntimeLifecycle, RuntimeState
    mock_lifecycle = RuntimeLifecycle()
    mock_lifecycle.transition(RuntimeState.PRECHECK)
    mock_lifecycle.transition(RuntimeState.RECOVER)
    mock_lifecycle.transition(RuntimeState.VERIFY_WAL)
    mock_lifecycle.transition(RuntimeState.VERIFY_WORKERS)
    mock_lifecycle.transition(RuntimeState.START_IPC)
    mock_lifecycle.transition(RuntimeState.START_SCHEDULER)
    mock_lifecycle.transition(RuntimeState.READY)
    
    supervisor = KernelSupervisor(mock_lifecycle, mock_event_bus, mock_recorder)
    
    violation = {
        "violation_number": 42,
        "code": "DIVERGENCE_DETECTED",
        "message": "Health score dropped below threshold",
        "payload": {"score": 0.85}
    }
    
    supervisor.on_violation(violation)
    
    # Assert FSM handled it correctly
    assert supervisor.lifecycle.current_state == RuntimeState.DEGRADED
    
    # Assert policy engine pushed STATE_DIVERGENCE
    published_events = [call[0][0]["type"] for call in mock_event_bus.publish.call_args_list]
    assert "STATE_DIVERGENCE" in published_events

@pytest.mark.asyncio
async def test_mid_replay_crash_simulation():
    """
    Simulates an incremental replay over a session log where a corrupted JSON line exists mid-stream.
    Asserts STRICT mode crashes, but DIAGNOSTIC mode skips and continues.
    """
    from core.replay.replay_engine import ReplayEngine, ReplayMode
    from core.replay.event_recorder import EventRecorder
    import tempfile
    import os
    from pathlib import Path

    temp_dir = Path(tempfile.mkdtemp())
    recorder = EventRecorder(log_dir=str(temp_dir), session_id="test_crash")
    await recorder.start()
    
    recorder.log_event("TEST", "core", "info", {"v": 1})
    await recorder.stop()
    
    log_dir = recorder.session_dir
    log_file = log_dir / "00000.jsonl"
    
    with open(log_file, "a", encoding="utf-8") as f:
        f.write("CORRUPT JSON LINE\n")

    try:
        engine = ReplayEngine(mode=ReplayMode.STRICT)
        with pytest.raises(ValueError, match="Corrupt data at"):
            list(engine._read_deltas(log_dir, 0))
            
        engine_diag = ReplayEngine(mode=ReplayMode.DIAGNOSTIC)
        events = list(engine_diag._read_deltas(log_dir, 0))
        assert len(events) == 1
    finally:
        import shutil
        shutil.rmtree(temp_dir)
