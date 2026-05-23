import asyncio
import websockets
import json
import time
import uuid

URI = "ws://127.0.0.1:8765"

async def simulate_crash_and_reconnect():
    print("\n--- Starting Phase E: Disconnect Recovery Simulation ---")
    try:
        print("[Client 1] Connecting to server...")
        # Create a connection, but we will purposefully not close it cleanly
        ws1 = await websockets.connect(URI)
        
        # Send a valid message to establish state
        msg = {
            "protocol_version": "1.0.0",
            "message_type": "EVENT",
            "event_type": "USER_COMMAND_ISSUED",
            "payload": {"text": "Start long running task"},
            "timestamp": time.time(),
            "msg_id": str(uuid.uuid4()),
            "correlation_id": str(uuid.uuid4())
        }
        await ws1.send(json.dumps(msg))
        print("[Client 1] Sent task trigger.")
        
        # Simulate abrupt client crash (network timeout / process kill)
        print("[Client 1] Simulating process kill (closing transport directly without websocket close frame)...")
        ws1.transport.close()
        
        # Wait for the server to detect timeout/EOF and clean up
        print("Waiting 3 seconds for server to clean up stale socket...")
        await asyncio.sleep(3)
        
        # Reconnect
        print("[Client 2] Reconnecting...")
        async with websockets.connect(URI) as ws2:
            print("[Client 2] Successfully reconnected!")
            # Wait for heartbeat to ensure we get authoritative state
            print("[Client 2] Waiting for authoritative heartbeat reconciliation...")
            heartbeat_found = False
            for _ in range(3):
                try:
                    response = await asyncio.wait_for(ws2.recv(), timeout=6.0)
                    data = json.loads(response)
                    if data.get("event_type") == "SYSTEM_HEARTBEAT":
                        auth_state = data.get("payload", {}).get("authoritative_state", {})
                        print(f"[Client 2] Received Heartbeat. Authoritative State: {auth_state}")
                        heartbeat_found = True
                        break
                except asyncio.TimeoutError:
                    continue
            
            if heartbeat_found:
                print("[Result] SUCCESS: Server survived abrupt disconnect and provided reconciliation state upon reconnect.")
            else:
                print("[Result] FAILED: Server reconnected but failed to send heartbeat reconciliation.")
                
    except Exception as e:
        import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
        print(f"Phase E Test Failed: {e}")

if __name__ == "__main__":
    asyncio.run(simulate_crash_and_reconnect())