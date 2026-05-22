import pytest
from core.contracts.runtime_states import RuntimeState
from core.bootstrap.runtime_lifecycle import RuntimeLifecycle

def test_lifecycle_initialization():
    lifecycle = RuntimeLifecycle()
    assert lifecycle.current_state == RuntimeState.BOOT

def test_valid_transitions():
    lifecycle = RuntimeLifecycle()
    lifecycle.transition(RuntimeState.PRECHECK)
    lifecycle.transition(RuntimeState.RECOVER)
    lifecycle.transition(RuntimeState.VERIFY_WAL)
    lifecycle.transition(RuntimeState.VERIFY_WORKERS)
    lifecycle.transition(RuntimeState.START_IPC)
    lifecycle.transition(RuntimeState.START_SCHEDULER)
    lifecycle.transition(RuntimeState.READY)
    lifecycle.transition(RuntimeState.QUIESCING)
    lifecycle.transition(RuntimeState.HALT)

def test_invalid_transitions():
    lifecycle = RuntimeLifecycle()
    # Cannot go from BOOT directly to READY
    with pytest.raises(Exception):
        lifecycle.transition(RuntimeState.READY)

def test_panic_from_anywhere():
    lifecycle = RuntimeLifecycle()
    lifecycle.transition(RuntimeState.PRECHECK)
    # PANIC is allowed from anywhere
    lifecycle.transition(RuntimeState.PANIC)
    
    lifecycle2 = RuntimeLifecycle()
    lifecycle2.transition(RuntimeState.PRECHECK)
    lifecycle2.transition(RuntimeState.RECOVER)
    lifecycle2.transition(RuntimeState.VERIFY_WAL)
    lifecycle2.transition(RuntimeState.VERIFY_WORKERS)
    lifecycle2.transition(RuntimeState.START_IPC)
    lifecycle2.transition(RuntimeState.START_SCHEDULER)
    lifecycle2.transition(RuntimeState.READY)
    lifecycle2.transition(RuntimeState.PANIC)
