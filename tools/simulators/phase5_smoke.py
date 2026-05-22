import sys
sys.path.insert(0, ".")

from shared.protocol.events import validate_message, PROTOCOL_VERSION
from core.foundation.canonical import canonical_dumps, state_hash
from core.runtime.runtime_auditor import RuntimeAuditor

# Test 1: canonical hash is deterministic
obj = {"b": 2, "a": 1, "ts": 1234567890.123456}
s1 = state_hash(obj)
s2 = state_hash(obj)
assert s1 == s2, "Hash not deterministic!"
print(f"[OK] canonical.state_hash deterministic: {s1[:16]}...")

# Test 2: new schema validates correctly
msg = {
    "protocol_version": "1.0.0",
    "message_type": "EVENT",
    "event_type": "AGENT_TASK_STARTED",
    "sequence_id": 42,
    "causal_parent_id": None,
    "payload": {"task_id": "abc"},
    "timestamp": 1234.0,
    "msg_id": "some-uuid",
    "correlation_id": "corr-uuid",
}
assert validate_message(msg), "Valid message rejected!"
print("[OK] validate_message accepts correct message")

# Test 3: old schema missing sequence_id is rejected
old = dict(msg)
del old["sequence_id"]
assert not validate_message(old), "Old schema without sequence_id should fail!"
print("[OK] validate_message rejects message missing sequence_id")

# Test 4: RuntimeAuditor catches illegal state transition
violations = []
auditor = RuntimeAuditor(supervisor_callback=lambda v: violations.append(v))
# Fire COMPLETED without prior STARTED — illegal
auditor.on_event({"event_type": "AGENT_TASK_COMPLETED", "task_id": "x", "msg_id": "msg1", "causal_parent_id": None})
auditor.on_event({"event_type": "AGENT_TASK_STARTED",   "task_id": "x", "msg_id": "msg2", "causal_parent_id": None})
assert len(violations) >= 1, "Expected at least one invariant violation!"
code = violations[0]["code"]
print(f"[OK] RuntimeAuditor caught illegal transition: {code}")

# Test 5: Duplicate msg_id triggers violation
violations2 = []
auditor2 = RuntimeAuditor(supervisor_callback=lambda v: violations2.append(v))
auditor2.on_event({"event_type": "AGENT_TASK_STARTED", "task_id": "t1", "msg_id": "dup-id", "causal_parent_id": None})
auditor2.on_event({"event_type": "AGENT_TOOL_CALL",   "task_id": "t1", "msg_id": "dup-id", "causal_parent_id": None})
assert any(v["code"] == "MSG_ID_DUPLICATE" for v in violations2), "Duplicate msg_id should trigger violation!"
print("[OK] RuntimeAuditor catches duplicate msg_id")

print()
print("All Phase 5 smoke tests PASSED.")
