import asyncio
import websockets
import json
import time
import uuid
import random
import tracemalloc

URI = "ws://127.0.0.1:8765"
DURATION_HOURS = 6

async def endurance_test():
    print(f"\n--- Starting Phase C: {DURATION_HOURS}-Hour Endurance Test ---")
    tracemalloc.start()
    
    snapshot1 = tracemalloc.take_snapshot()
    start_time = time.time()
    end_time = start_time + (DURATION_HOURS * 3600)
    
    msg_count = 0
    try:
        async with websockets.connect(URI) as ws:
            while time.time() < end_time:
                # Simulate constant traversal and random agent events
                msg = {
                    "protocol_version": "1.0.0",
                    "message_type": "EVENT",
                    "event_type": random.choice([
                        "AGENT_TOOL_CALL", "AGENT_TASK_STARTED", "AGENT_TASK_COMPLETED", "SCENE_LOAD"
                    ]),
                    "payload": {"iteration": msg_count, "simulated_data": [random.random() for _ in range(100)]},
                    "timestamp": time.time(),
                    "msg_id": str(uuid.uuid4()),
                    "correlation_id": str(uuid.uuid4())
                }
                await ws.send(json.dumps(msg))
                msg_count += 1
                
                # Sleep to simulate realistic sporadic workload (approx 10 msg/sec)
                await asyncio.sleep(0.1)
                
                if msg_count % 10000 == 0:
                    elapsed = time.time() - start_time
                    snapshot2 = tracemalloc.take_snapshot()
                    top_stats = snapshot2.compare_to(snapshot1, 'lineno')
                    
                    print(f"[{elapsed/3600:.2f}h] Sent {msg_count} msgs. Memory Diff Top 3:")
                    for stat in top_stats[:3]:
                        print(stat)
                        
                    # Reset snapshot to watch for continuous growth, not just initial allocation
                    snapshot1 = snapshot2
                    
    except Exception as e:
        print(f"Endurance test failed prematurely: {e}")
        
    print("\n--- Endurance Test Complete ---")
    print(f"Total Messages: {msg_count}")
    
if __name__ == "__main__":
    asyncio.run(endurance_test())
