# NovaMind Audit — Godot Client, Bridge, and Integration Layer

**Audit date:** 2026-10-06  
**Scope:** `godot_client/`, `integrations/godot/`, `core/ipc/bridge_server.py` and related IPC.  
**Method:** Godot `.gd`/`.tscn`/`.godot` files read directly; Python bridge and protocol files read directly.

---

## 1. The Godot client is a small spatial shell, not a full game

Files:

- `godot_client/project.godot` — engine config; `run/main_scene="res://Main.tscn"`; autoload `NetworkManager="*res://NetworkManager.gd"`; window `1280×720`; input map defines `move_forward/backward/left/right`, `jump`, `toggle_camera`, `toggle_terminal`.
- `godot_client/Main.tscn` — single `Node` with `Main.gd`.
- `godot_client/Main.gd` — boots `CommandHub`, `Player`, `AgentVisualizer`, `DiagnosticsOverlay`, and a `Terminal` overlay (loaded script attached to a `Control` node inside a `CanvasLayer`).
- `godot_client/NetworkManager.gd` — WebSocket client to `ws://127.0.0.1:8765`, reconnects on close, parses JSON, emits `event_received`/`state_updated` signals, handles `HEARTBEAT` pong.
- `godot_client/player/Player.gd` — `CharacterBody3D` with capsule mesh + camera spring arm; first/third person toggle; WASD + jump.
- `godot_client/visualizer/AgentVisualizer.gd` — `Node3D` that spawns/despawns agent "holograms" (cylinder meshes + `Label3D`) on `state_updated` events with actions `task_started`, `task_completed`, `task_failed`, `tool_call_start`, `tool_call_end`.
- `godot_client/world/CommandHub.gd` — `Node3D` that sets up directional light, `Environment` (procedural sky, SSAO), and a `VoxelTerrain` with `VoxelGeneratorFlat` + `VoxelMesherBlocky`. This is a voxel terrain, not the Ursina city.
- `godot_client/Terminal.gd` — `Control` overlay: `RichTextLabel` output log + `LineEdit` input; on submit sends `NetworkManager.send_message("EVENT", "user_command", {"text": text})`; also has a 2-second timer that auto-sends `"open my vscode workspace"` as a vertical-slice test.
- `godot_client/DiagnosticsOverlay.gd` — `CanvasLayer` diagnostics panel showing FPS, static memory, IPC status, protocol version, latency, dropped packets. Reads `NetworkManager` socket state.
- `godot_client/help.txt`, `godot_client/godot_out.txt` — empty.

So the Godot client is a lightweight spatial visualization/shell: voxel terrain + player + agent holograms + terminal overlay + diagnostics. It is **not** the large "Nova City" Ursina game.

---

## 2. The Python-side bridge

### 2.1 `core/ipc/bridge_server.py`

- WebSocket server on `127.0.0.1:8765` (`websockets` library).
- `BridgeServer` is framed as a **CQRS** boundary: Godot commands are "fire-and-forget Intent submissions"; UI observations are loss-tolerant egress.
- Message shape it sends:

```python
msg = {
    "protocol_version": PROTOCOL_VERSION,
    "message_type": msg_type,
    "event_type": event_type,
    "sequence_id": seq,
    "payload": payload or {},
    "timestamp": time.time(),
    "msg_id": mid,
    "correlation_id": str(uuid.uuid4()),
}
```

- Incoming message shape it **expects** (from `shared/protocol/events.py` validation) plus sequence-number handling with out-of-order queue, idempotent `msg_id` dedupe (deque maxlen 4096), chaos mode that randomly drops, and egress loop reading from `RuntimeEventStream`.

### 2.2 `shared/protocol/events.py` and `shared/protocol/schema.json`

- `shared/protocol/events.py` defines `MessageType`, `EventType`, `PROTOCOL_VERSION = "1.1.0"`, and a `validate_message` function used by the bridge.
- `shared/protocol/schema.json` is the protocol schema doc (read as part of the top-level audit; it describes the IPC schema).

These are the "official" cross-process protocol definitions. They are real, but the Godot client does **not** use them verbatim.

---

## 3. The integration layer under `integrations/godot/`

- `integrations/godot/godot_bridge_protocol.py` — defines `GodotMessageType` (`TASK_CREATED`, `WORKER_PANIC`, `APPROVAL_REQUEST`, `TELEMETRY_UPDATE`), `GodotMessagePriority` (`UI_PRIORITY`, `BACKGROUND_PRIORITY`, `CRITICAL_PRIORITY`), and `GodotTelemetryMessage`.
- `integrations/godot/godot_transport.py` — a queue-based transport with priority-based dropping policies; no actual network code; it is a local modeling of backpressure.
- `integrations/godot/mission_projection.py` — pure read-only mappers from `IntentStatus` / worker panic into `GodotTelemetryMessage`.

These modules describe the **intended** Godot integration contract, but the live Godot client in `godot_client/` speaks its own message shape, and the Python bridge speaks its own. The `integrations/godot/` modules are not the active transport used by either side as read.

---

## 4. Concrete message-shape mismatch

### 4.1 Godot client sends

From `Terminal.gd`:

```gdscript
NetworkManager.send_message("EVENT", "user_command", {"text": text})
```

which builds:

```gdscript
var message = {
    "type": "EVENT",
    "action": "user_command",
    "payload": {"text": text},
    "timestamp": ...,
    "msg_id": ...
}
```

### 4.2 Python bridge sends

From `bridge_server.py` (egress) it sends `message_type`, `event_type`, `sequence_id`, `correlation_id`, etc. as in section 2.1.

### 4.3 Python `main.py` handler expects

```python
async def on_godot_command(data):
    event_type = data.get("event_type")
    ...
    if event_type == "USER_COMMAND_ISSUED":
        ...
self.bridge_server.register_handler("EVENT", on_godot_command)
```

So `main.py` reads `data["event_type"]` and compares it to `"USER_COMMAND_ISSUED"`. But the Godot client sends `action = "user_command"` and `type = "EVENT"`, and the Python bridge's incoming frame would have `message_type` and `payload` shaped by the Godot client's JSON, not by the Python-side envelope fields.

**Evidence:** the field names differ (`type` vs `message_type`; `action` vs `event_type`), and the command strings differ (`"user_command"` vs `"USER_COMMAND_ISSUED"`). As written, the Godot client's message would not drive the `main.py` vertical-slice handler the way the handler assumes.

---

## 5. Vertical-slice test baked into the Godot client

`Terminal.gd` has:

```gdscript
var timer = Timer.new()
timer.wait_time = 2.0
timer.one_shot = true
timer.timeout.connect(func(): _on_text_submitted("open my vscode workspace"))
add_child(timer)
timer.start()
```

So when the Godot client starts, 2 seconds in it auto-sends the command `"open my vscode workspace"`. That is a real vertical-slice smoke test baked into the client.

The corresponding `main.py` handler reacts to `"USER_COMMAND_ISSUED"` with text containing `"workspace"` or `"vscode"` and tries to:

- request OS permission via `PermissionManager`,
- send a STATE_UPDATE to Godot,
- launch `code .` via `asyncio.create_subprocess_shell("code .", cwd=...)`,
- send another STATE_UPDATE.

That path is real Python code; whether it actually runs end-to-end depends on the bridge being up, the message shape matching, and `PermissionManager` returning `True` (it does return `True` in the current code via a dev override, as read).

---

## 6. The bridge is real but only partially integrated

- `core/ipc/bridge_server.py` is a real WebSocket server with sequence handling, dedupe, chaos mode, egress from `RuntimeEventStream`.
- `main.py` starts it on a dedicated asyncio thread: `loop.run_until_complete(_start_all())` where `_start_all` starts `TaskManager`, `EventRecorder`, and `BridgeServer`.
- The bridge is the IPC spine between Python and the Godot client.
- But the two sides' message contracts are not aligned as read, and the "kernel/intent" path is not what the bridge is carrying in `main.py` (it is carrying Brain/agent events, not `ExecutionIntent` traffic through the kernel facade).

---

## 7. Two different "games" in the repo

- `legacy_game/nova_mindscape.py` — the large Ursina "NOVA CITY" open-world cyberpunk city. This is what `SETUP.md` and `main.py`'s older comments refer to when they say "3D game".
- `godot_client/` — the smaller Godot 4 spatial shell described above.

`main.py` has a `self.game` attribute and `_on_game_task_update`, but it does not clearly pick one engine. The repo therefore has two candidate front ends and does not decisively choose between them.

---

## 8. Bottom line for integration

- There is a real WebSocket bridge and a real Godot client.
- There is a real (but not yet aligned) protocol in `shared/protocol/` and a real integration model in `integrations/godot/`.
- As read, the Godot client and the Python bridge do **not** share an identical message shape, and `main.py`'s handler expects a command string the Godot client does not send.
- This is consistent with foundation stage: the pieces exist, but the cross-process contract is not yet verified.
