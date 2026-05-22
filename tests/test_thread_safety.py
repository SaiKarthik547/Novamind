import asyncio
import threading
import time
import random
import uuid
import websockets
from concurrent.futures import ThreadPoolExecutor

from core.bridge_server import BridgeServer

HOST = "127.0.0.1"
PORT = 8766  # Use a different port to avoid conflict with daemon

async def mock_client():
    """Acts as Godot to receive messages."""
    received = 0
    try:
        async with websockets.connect(f"ws://{HOST}:{PORT}") as ws:
            print("[Client] Connected. Ready to receive storm.")
            start_time = time.time()
            try:
                while True:
                    await asyncio.wait_for(ws.recv(), timeout=5.0)
                    received += 1
            except asyncio.TimeoutError:
                pass # Storm is over
            print(f"[Client] Storm ended. Received {received} messages in {time.time() - start_time:.2f}s")
    except Exception as e:
        print(f"[Client] Error: {e}")
    return received

def thread_worker(bridge: BridgeServer, worker_id: int, num_events: int):
    """Fires uneven threadsafe events from a background thread."""
    success = 0
    for i in range(num_events):
        # Uneven delays to cause race conditions
        time.sleep(random.uniform(0.0001, 0.005))
        
        ok = bridge.send_message_threadsafe(
            msg_type="STATE_UPDATE",
            event_type="AGENT_TASK_STARTED",
            payload={"worker": worker_id, "iter": i},
            correlation_id=str(uuid.uuid4())
        )
        if ok:
            success += 1
            
    print(f"[Thread {worker_id}] Sent {success}/{num_events} messages safely.")

async def main():
    bridge = BridgeServer(host=HOST, port=PORT)
    await bridge.start()
    
    client_task = asyncio.create_task(mock_client())
    await asyncio.sleep(1) # wait for connect
    
    num_threads = 10
    events_per_thread = 500
    
    print(f"\n--- Starting Phase B: Thread Storm ({num_threads} threads, {events_per_thread} events each) ---")
    
    start_time = time.time()
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        for i in range(num_threads):
            executor.submit(thread_worker, bridge, i, events_per_thread)
            
    elapsed = time.time() - start_time
    print(f"\n[Storm] Threads finished firing in {elapsed:.2f}s. Waiting for client to drain queue...")
    
    total_received = await client_task
    expected = num_threads * events_per_thread
    
    print(f"\n[Result] Expected: {expected}, Received: {total_received}")
    if total_received >= expected: # Might be slightly higher if heartbeat is received
        print("[Result] SUCCESS: All threadsafe messages successfully marshalled across boundaries.")
    else:
        print("[Result] FAILED: Race condition detected. Messages dropped.")
        
    await bridge.stop()

if __name__ == "__main__":
    asyncio.run(main())
