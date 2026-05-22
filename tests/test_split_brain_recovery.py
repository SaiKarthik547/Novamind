import pytest
import time
import asyncio
from unittest.mock import MagicMock

from core.replay.divergence_analyzer import DivergenceAnalyzer
from core.runtime.runtime_supervisor import RuntimeSupervisor, SupervisorMode

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
    supervisor = RuntimeSupervisor(mock_event_bus, mock_recorder)
    
    violation = {
        "violation_number": 42,
        "code": "DIVERGENCE_DETECTED",
        "message": "Health score dropped below threshold",
        "payload": {"score": 0.85}
    }
    
    supervisor.on_violation(violation)
    
    # Assert FSM handled it correctly
    assert supervisor.fsm.mode == SupervisorMode.DEGRADED
    
    # Assert policy engine pushed STATE_DIVERGENCE
    published_events = [call[0][0]["type"] for call in mock_event_bus.publish.call_args_list]
    assert "STATE_DIVERGENCE" in published_events

def test_mid_replay_crash_simulation():
    """
    Simulates an incremental replay over a session log where a corrupted JSON line exists mid-stream.
    Asserts STRICT mode crashes, but DIAGNOSTIC mode skips and continues.
    """
    from core.replay_engine import ReplayEngine, ReplayMode
    import tempfile
    import json
    from pathlib import Path
    
    with tempfile.NamedTemporaryFile("w+", delete=False) as tf:
        tf.write(json.dumps({"sequence_id": 1, "payload": {}}) + "\n")
        tf.write("CORRUPT JSON LINE\n")
        tf.write(json.dumps({"sequence_id": 3, "payload": {}}) + "\n")
        log_path = Path(tf.name)
        
    try:
        engine = ReplayEngine(mode=ReplayMode.STRICT)
        with pytest.raises(ValueError, match="Corrupt JSON"):
            list(engine._read_deltas(log_path, 0))
            
        engine_diag = ReplayEngine(mode=ReplayMode.DIAGNOSTIC)
        events = list(engine_diag._read_deltas(log_path, 0))
        assert len(events) == 2 # 1 and 3
        
    finally:
        log_path.unlink()
