"""
tests/test_chaos_injector.py
Tier 1 Chaos Injection — Transport-level adversarial testing.

Tests:
  1. Packet drops (20%)
  2. Packet duplication (20%)
  3. Burst followed by silence (tests queue depth under load)
  4. Out-of-order sequence injection (tests bounded reconciliation)
  5. Reconnect during active task stream (hardest distributed problem)

DOES NOT perform payload mutation (Tier 2 — handled separately in CI only).

Usage:
    $env:PYTHONPATH="."; py tests/test_chaos_injector.py
"""

import asyncio
import json
import random
import time
import uuid
import websockets

URI = "ws://127.0.0.1:8765"
PROTO = "1.0.0"

_seq = 0
def _next_seq():
    global _seq
    s = _seq
    _seq += 1
    return s

def _msg(event_type: str, payload: dict = None, seq: int = None, causal: str = None):
    return json.dumps({
        "protocol_version": PROTO,
        "message_type": "EVENT",
        "event_type": event_type,
        "sequence_id": seq if seq is not None else _next_seq(),
        "causal_parent_id": causal,
        "payload": payload or {},
        "timestamp": time.time(),
        "msg_id": str(uuid.uuid4()),
        "correlation_id": str(uuid.uuid4()),
    })


# ── Test 1: Packet Drop Simulation ───────────────────────────────────────────

async def test_drop(ws, total=200, drop_rate=0.2):
    dropped = 0
    for _ in range(total):
        if random.random() < drop_rate:
            dropped += 1
            _next_seq()  # Advance seq counter without sending → forces server-side gap
            continue
        await ws.send(_msg("USER_COMMAND_ISSUED", {"text": "chaos drop test"}))
    print(f"[Drop Test]   Dropped {dropped}/{total} intentionally. Server should enter degraded mode for gaps.")


# ── Test 2: Packet Duplication ────────────────────────────────────────────────

async def test_duplicate(ws, total=100, dup_rate=0.2):
    duped = 0
    for _ in range(total):
        m = _msg("AGENT_TASK_STARTED", {"task_id": f"t_{uuid.uuid4().hex[:6]}"})
        await ws.send(m)
        if random.random() < dup_rate:
            duped += 1
            await ws.send(m)  # Same msg (same msg_id) — must be silently discarded
    print(f"[Dup Test]    Sent {duped} duplicates. Server idempotency must discard all.")


# ── Test 3: Burst + Silence ───────────────────────────────────────────────────

async def test_burst_silence(ws, burst=500):
    start = time.time()
    for _ in range(burst):
        await ws.send(_msg("AGENT_TOOL_CALL"))
    await asyncio.sleep(3)  # Silence — let queue drain
    elapsed = time.time() - start
    print(f"[Burst+Silence] {burst} msgs burst in {elapsed:.2f}s. Server must handle cleanly.")


# ── Test 4: Deliberate Out-of-Order Sequence ──────────────────────────────────

async def test_ooo(ws):
    """Send seq 0,1,2,5,3,4 — testing bounded reconciliation (not hard disconnect in prod mode)."""
    base = _next_seq()
    ordered = [base, base+1, base+2, base+5, base+3, base+4]
    # Globally advance seq to keep future messages consistent
    for _ in range(5):
        _next_seq()

    for s in ordered:
        await ws.send(_msg("USER_COMMAND_ISSUED", {"text": "ooo test"}, seq=s))
        await asyncio.sleep(0.05)
    print(f"[OOO Test]    Sent seq {ordered}. Bounded reconciliation should drain correctly.")


# ── Test 5: Reconnect Mid-Stream ──────────────────────────────────────────────

async def test_reconnect_mid_stream():
    """Open a connection, fire tasks, abruptly close, reconnect and check heartbeat state."""
    global _seq
    _seq = 0  # Reset seq for new connection

    print("[Reconnect]   Phase 1: Connect and fire tasks...")
    ws = await websockets.connect(URI)
    corr = str(uuid.uuid4())
    for i in range(50):
        await ws.send(_msg("AGENT_TASK_STARTED", {"task_id": f"task_{i}", "text": "mid-stream"}, causal=None))
        await asyncio.sleep(0.01)

    print("[Reconnect]   Phase 2: Abruptly closing transport (simulated crash)...")
    ws.transport.close()
    await asyncio.sleep(2)

    print("[Reconnect]   Phase 3: Reconnecting...")
    _seq = 0  # New connection = new sequence stream
    async with websockets.connect(URI) as ws2:
        print("[Reconnect]   Phase 4: Awaiting authoritative heartbeat...")
        for _ in range(4):
            try:
                raw = await asyncio.wait_for(ws2.recv(), timeout=6.0)
                data = json.loads(raw)
                if data.get("event_type") == "SYSTEM_HEARTBEAT":
                    state = data.get("payload", {}).get("authoritative_state", {})
                    print(f"[Reconnect]   Heartbeat received. State: {state}")
                    break
            except asyncio.TimeoutError:
                continue
        else:
            print("[Reconnect]   FAILED: No heartbeat received after reconnect.")
            return
        print("[Reconnect]   SUCCESS: Server survived mid-stream reconnect and provided state.")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    print("\n=== NovaMind Chaos Injector — Tier 1 Transport Chaos ===\n")

    # Tests 1-4 on a single connection
    try:
        async with websockets.connect(URI) as ws:
            await test_drop(ws)
            await asyncio.sleep(0.5)
            await test_duplicate(ws)
            await asyncio.sleep(0.5)
            await test_burst_silence(ws)
            await asyncio.sleep(0.5)
            await test_ooo(ws)
            await asyncio.sleep(1.0)
    except Exception as e:
        import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
        print(f"[Chaos] Connection failed for tests 1-4: {e}")

    await asyncio.sleep(2)

    # Test 5 needs its own connection lifecycle
    try:
        await test_reconnect_mid_stream()
    except Exception as e:
        import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
        print(f"[Reconnect] Test failed: {e}")

    print("\n=== Chaos Injection Complete ===")


if __name__ == "__main__":
    asyncio.run(main())