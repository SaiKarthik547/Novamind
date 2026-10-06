# NovaMind Audit — Legacy Game, Legacy Compat, and Persisted Artifacts

**Audit date:** 2026-10-06  
**Scope:** `legacy_game/`, `legacy_compat/`, and top-level persisted artifacts (`nova_effect.wal`, `runtime_snapshot.json`, `.novamind/`).  
**Method:** files read directly; where a file is large, the audit characterizes the real parts that were read and flags the rest as not fully verified.

---

## 1. `legacy_game/` — the Ursina "Nova Mindscape"

### 1.1 `legacy_game/__init__.py`

Empty.

### 1.2 `legacy_game/nova_mindscape.py`

This is a large, real Ursina open-world cyberpunk city ("NOVA CITY"). It is the "3D game" referenced in older docs and in `main.py`'s comments about a single game window.

What is real and read in detail:

- `GameConfig` dataclass with title, fullscreen, vsync, window size (`1440×900`), FOV, move/sprint/look speeds, rain/NPC/vehicle/shard counts.
- `STATUS_RGB` mapping from task status strings to color tuples: `pending`, `running`, `retrying`, `verifying`, `success`, `done`, `failed`, `cancelled`, `recurring`.
- City grid constants: `GRID_COLS = 6`, `BLOCK_SIZE = 24`, `ROAD_W = 14`, block centers and road centers computed from those.
- `NovaMindscape` class with:
  - thread-safe `update_tasks(tasks: List[Dict])` (uses a lock).
  - player physics fields (`_cam_yaw`, `_vy`, `_on_ground`, `_bob_phase`, `_third_person`, `_cam_shake`).
  - scene object collections (`_rain`, `_npcs`, `_vehicles`, `_shards`, `_beacons`, `_terminals`, `_neon_signs`, `_win_strips`, `_stars`, `_moon`, `_lightning_*`).
  - HUD refs (`_hud_mission`, `_hud_status`, `_hud_xp`, `_hud_cash`, `_hud_stars`, `_hud_interact`, `_hud_level_up`, `_hud_notify`, `_minimap_*`).
- `run_blocking()` — the correct Ursina entry point: builds `Ursina()`, applies `config.py` performance overrides (`GAME_RESOLUTION`, `GAME_LOW_PERF_MODE`, `GAME_RAIN_COUNT`, `GAME_NPC_COUNT`, `GAME_VEHICLE_COUNT`), builds scene, then `app.run()`.
- `_build_scene()` — builds sky (stars, moon, distant mountains, cloud/smog planes), lighting (ambient + directional + neon point lights at intersections), terrain (asphalt ground, canal, water shimmer, bridge), roads (E-W and N-S road quads, center-line dashes, sidewalks, intersection blocks, traffic-light poles), buildings (towers, corporate, hotel, apartment, club, warehouse, industrial with window strips, rooftop neon, antennas, blinking lights), AI tower, elevated highway, monorail, street details.
- Monkeypatched `Entity.__init__` during scene build to auto-assign static cubes to combined meshes by color heuristics, then restored in `finally`.
- `combine()` on the four combined mesh entities for FPS.
- HUD build, minimap build, player setup, cinematic intro.

So this is a substantial real game, not a stub. It is also explicitly labeled "legacy" by its location and by the presence of `legacy_compat/`.

### 1.3 `legacy_game/nova_mindscape_launcher.py` and `texture_gen.py`

Both read partially; they are support files for the Ursina game (launcher and procedural texture generation). They are real but not central to the kernel story.

---

## 2. `legacy_compat/legacy_ui_adapter.py`

- Implements `LegacyUIAdapter` (an `ApplicationAdapter`).
- Explicit about being **DEPRECATED** and **NON_DETERMINISTIC**: it seizes the active desktop via `pyautogui`, and its `execute` logs *"Execution lineage downgraded: NON_DETERMINISTIC"*.
- `verify` returns `mode == VerificationMode.SEMANTIC` (i.e. it assumes true but calls itself unreliable).
- `reconcile` returns `False`.

This adapter is the bridge between the old desktop-automation world and the new adapter-contract world. It exists, but it is explicitly marked as transitional/legacy.

---

## 3. Top-level persisted artifacts

### 3.1 `nova_effect.wal`

This is the default `wal_path` for `KernelSupervisor` (runtime/) and is referenced as the side-effect WAL. Its presence at the repo root suggests it is a real (possibly empty or stub) WAL file from prior runs. It is part of the kernel story, not the desktop-assistant story.

### 3.2 `runtime_snapshot.json`

Contains:

- `authority_graph`: `runtime_fsm → RuntimeKernel`, `wal_journal → RecoveryJournal`, `lock_orchestration → ResourceLockManager`.
- `capability_topology`: a full capability table (filesystem.read/write/delete/mkdir, process.spawn/kill, network.http_request, process.kill, shell.execute, ui.hotkey/keyboard_type/click/screenshot) with `determinism_class`, `replay_policy`, `rollback_policy`, `authority_level`, `trust_level`, `requires_user_focus`, `allows_background_execution`, `side_effect_permanent`, `verification_mode`.

This file is essentially a persisted version of the capability topology that `core/execution/capability_registry.py` defines in code. It is evidence that the capability-topology concept is real and was serialized at some point.

### 3.3 `runtime/session_registry.json` and `.novamind/` artifacts

- `runtime/session_registry.json` contains a list of past session objects with `session_id` and `status: "active"`. This matches `SessionRegistry`'s JSON format.
- `.novamind/kernel/recovery.wal` and `.novamind/logs/novamind_20260513.log` are real persisted artifacts from prior runs.
- `.local/audit_memory_fresh.db` and `.local/audit_memory_stale.db` are SQLite artifacts; their presence suggests audit/memory tooling ran at some point.

These artifacts show the system has been exercising persistence (sessions, WAL, logs, DBs). That is real, but it does not by itself prove a complete kernel+UI+backend+frontend path.

---

## 4. What "legacy" means in this repo

- `legacy_game/` is the older 3D game (Ursina).
- `legacy_compat/legacy_ui_adapter.py` is the older desktop-UI automation shim.
- The word "legacy" here is being used for two different things: an older **presentation/game** layer, and an older **UI-automation** adapter. Both are real; both are marked as superseded by the newer architecture, but neither has a clearly defined replacement that is fully wired.

---

## 5. Skeleton signals in the legacy area

- The "new" Godot client (`godot_client/`) coexists with the "legacy" Ursina game without a clear choice between them.
- The legacy UI adapter is real but returns unverified results and is marked non-deterministic.
- Persisted artifacts exist, but they are artifacts, not proof of a currently-working integrated system.
