import asyncio
import websockets
import json
import time
import uuid
import random
import sys

URI = "ws://127.0.0.1:8765"

async def fuzz_payloads(websocket):
    print("\n--- Starting Phase A: Schema Fuzzing ---")
    malformed_schemas = [
        {},  # Empty
        {"protocol_version": "0.9.0"},  # Wrong version
        {"protocol_version": "1.0.0", "message_type": "INVALID_ENUM", "event_type": "UNKNOWN"}, # Wrong Enums
        {"protocol_version": "1.0.0", "message_type": "EVENT", "event_type": "AGENT_TOOL_CALL", "payload": "Not an object"} # Wrong type
    ]
    
    for i, payload in enumerate(malformed_schemas):
        try:
            await websocket.send(json.dumps(payload))
            print(f"[Fuzz {i}] Sent malformed payload. Waiting for response...")
            # We expect the server to force disconnect us (code 1003)
            await asyncio.sleep(0.5)
        except websockets.exceptions.ConnectionClosed as e:
            print(f"[Fuzz {i}] SUCCESS: Server forcefully disconnected us with code {e.code}.")
            return # We successfully triggered the force disconnect!
    
    print("FAILED: Server did not disconnect us on malformed payload.")

async def flood_test():
    print("\n--- Starting Phase A: 10k Burst Flood ---")
    try:
        async with websockets.connect(URI) as websocket:
            start_time = time.time()
            for i in range(10000):
                msg = {
                    "protocol_version": "1.0.0",
                    "message_type": "EVENT",
                    "event_type": "USER_COMMAND_ISSUED",
                    "payload": {"text": f"Flood message {i}"},
                    "timestamp": time.time(),
                    "msg_id": str(uuid.uuid4()),
                    "correlation_id": str(uuid.uuid4())
                }
                await websocket.send(json.dumps(msg))
                # Optional: uneven delay injection to simulate real load
                if random.random() < 0.05:
                    await asyncio.sleep(0.001)

            elapsed = time.time() - start_time
            print(f"Sent 10,000 valid messages in {elapsed:.4f} seconds.")
            print(f"Throughput: {10000/elapsed:.2f} msg/sec.")
            
    except Exception as e:
        print(f"Flood test failed: {e}")

async def main():
    print("Connecting for Fuzz Test...")
    try:
        async with websockets.connect(URI) as ws:
            await fuzz_payloads(ws)
    except Exception as e:
        print(f"Could not connect: {e}")
        
    await asyncio.sleep(1)
    await flood_test()

if __name__ == "__main__":
    asyncio.run(main())
