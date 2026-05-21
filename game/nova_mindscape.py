"""
╔══════════════════════════════════════════════════════════════════╗
║   NOVA CITY  —  Nova Mindscape v3.0                             ║
║   AAA-grade open-world cyberpunk city built with Ursina          ║
╠══════════════════════════════════════════════════════════════════╣
║  You are Agent NOVA.  NovaMind's running tasks appear as LIVE   ║
║  mission objectives in a dense neon city.  Walk to them.        ║
║  Complete them.  Own the city.                                  ║
╠══════════════════════════════════════════════════════════════════╣
║  Controls                                                        ║
║  ─────────                                                       ║
║  WASD / Arrows  — move              Space  — jump               ║
║  Mouse          — look/aim          Shift  — sprint             ║
║  F              — interact (near terminal / mission)            ║
║  V              — toggle 1st / 3rd person                       ║
║  M              — toggle minimap                                ║
║  T              — toggle task feed                              ║
║  R              — manual refresh                                ║
║  ESC            — quit                                          ║
╠══════════════════════════════════════════════════════════════════╣
║  pip install ursina                                              ║
╚══════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import math
import random
import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Callable

logger = logging.getLogger("NovaMindscape")

# ── Ursina import guard ───────────────────────────────────────────────────────
try:
    from ursina import (
        Ursina, Entity, camera, Sky, color, Vec3, Vec2,
        held_keys, Text, window, mouse, application, invoke, destroy,
        InputField
    )
    # Fix: Ursina 3 color.rgba doesn't normalize 0-255 values, causing everything to be >1.0
    # and rendering as pure blown-out white/black void. Alias it to rgba32 which divides by 255.
    if hasattr(color, 'rgba32'):
        color.rgba = color.rgba32

    from ursina.prefabs.first_person_controller import FirstPersonController
    URSINA_OK = True
except ImportError:
    URSINA_OK = False
    logger.warning("ursina not installed — 3D game unavailable. pip install ursina")

try:
    from ursina import AmbientLight, DirectionalLight, PointLight, SpotLight
    URSINA_LIGHTS = True
except ImportError:
    URSINA_LIGHTS = False

try:
    from ursina import Audio
    URSINA_AUDIO = True
except ImportError:
    URSINA_AUDIO = False


# ─────────────────────────────────────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class GameConfig:
    title:         str   = "NOVA CITY  —  NovaMind"
    fullscreen:    bool  = False
    vsync:         bool  = True
    dev_mode:      bool  = False
    window_size:   tuple = (1440, 900)
    fov:           int   = 85
    move_speed:    float = 7.0
    sprint_speed:  float = 14.0
    look_speed:    float = 55.0
    rain_count:    int   = 280
    npc_count:     int   = 22
    vehicle_count: int   = 14
    shard_count:   int   = 28
    enable_rain:   bool  = True
    enable_traffic: bool = True
    enable_npcs:   bool  = True


# ─────────────────────────────────────────────────────────────────────────────
#  Status → colour mapping  (0-255 int tuples)
# ─────────────────────────────────────────────────────────────────────────────

STATUS_RGB: Dict[str, Tuple[int, int, int]] = {
    "pending":   (80,  80, 110),
    "running":   (0,  212, 255),
    "retrying":  (255, 185,   0),
    "verifying": (59, 130, 246),
    "success":   (34, 197,  94),
    "done":      (34, 197,  94),
    "failed":    (239,  68,  68),
    "cancelled": (55,  55,  55),
    "recurring": (0,  230, 178),
}
_RGB_DEFAULT = (90, 90, 90)

# ── Module-level O(1) dispatch / lookup tables ────────────────────────────────

# Camera mode settings — dict replaces if/else branching (True=3rd-person)
_CAM_MODE_SETTINGS: Dict[bool, Dict] = {
    True:  {"cam_pos": (0.0, 1.0, -8.0), "cam_rot": (8, 0, 0), "player_vis": True},
    False: {"cam_pos": (0.0, 0.0,  0.1), "cam_rot": (0, 0, 0), "player_vis": False},
}

# Interaction prompt builders — dict dispatch replaces if/elif/else
_INTERACT_PROMPTS: Dict[str, Callable] = {
    "terminal": lambda _: "  [F]  READ TERMINAL  ",
    "beacon":   lambda d: (
        f"  [F]  VIEW MISSION  "
        f"[{((d or {}).get('task') or {}).get('status','?').upper()}]  "
    ),
}

# Task status symbols for HUD feed
_HUD_SYMS: Dict[str, str] = {
    "running":   ">",  "success":  "*",  "done":      "*",
    "failed":    "x",  "pending":  ".",  "retrying":  "~",
    "verifying": "O",  "cancelled":"-",
}

# Star-rating colours indexed by star count 0-5
_STAR_COLS = [
    (255,  50,  50),   # 0
    (255,  50,  50),   # 1 ★
    (255,  50,  50),   # 2 ★★
    (255, 200,   0),   # 3 ★★★
    (255, 200,   0),   # 4 ★★★★
    (  0, 212, 255),   # 5 ★★★★★
]

# Dispatch: status string → beacon colour helper (O(1) dict lookup)
_BEACON_ALPHA: Dict[str, int] = {k: 210 for k in STATUS_RGB}
_BEACON_ALPHA["failed"] = 140


def _ucol(status: str, alpha: int = 210):
    r, g, b = STATUS_RGB.get(status, _RGB_DEFAULT)
    return color.rgba(r, g, b, alpha)


def _rgb(status: str) -> Tuple[int, int, int]:
    return STATUS_RGB.get(status, _RGB_DEFAULT)


# ─────────────────────────────────────────────────────────────────────────────
#  City grid constants
# ─────────────────────────────────────────────────────────────────────────────
# 6 × 6 blocks, block size 24, road width 14
# Block centres:  -95, -57, -19,  19,  57,  95
# Road centres:   -76, -38,   0,  38,  76

GRID_COLS  = 6
BLOCK_SIZE = 24
ROAD_W     = 14
STEP       = BLOCK_SIZE + ROAD_W

_BCENTRES = [-95 + i * STEP for i in range(GRID_COLS)]   # [-95,-57,-19,19,57,95]
_RCENTRES = [(_BCENTRES[i] + _BCENTRES[i+1]) / 2         # road x/z between blocks
             for i in range(GRID_COLS - 1)]


# ─────────────────────────────────────────────────────────────────────────────
#  Main game class
# ─────────────────────────────────────────────────────────────────────────────

class NovaMindscape:
    """
    Open-world cyberpunk city.  All scene building and per-frame logic lives here.
    update_tasks() is thread-safe — call it from Brain callbacks freely.
    """

    def __init__(self, config: GameConfig = None,
                 task_callback: Optional[Callable] = None):
        self.config        = config or GameConfig()
        self.task_callback = task_callback
        self._running      = False
        self._tasks: List[Dict] = []
        self._lock  = threading.Lock()

        # ── Game state ──────────────────────────────────────────────────
        self._score       = 0
        self._xp          = 0
        self._level       = 1
        self._cash        = 0
        self._agent_stars = 5

        # ── Player physics ──────────────────────────────────────────────
        self._cam_yaw    = 0.0
        self._cam_pitch  = 10.0
        self._vy         = 0.0
        self._on_ground  = True
        self._bob_phase  = 0.0
        self._third_person = True
        self._cam_shake    = 0.0

        # ── Scene object collections ─────────────────────────────────────
        self._player:   Optional[Entity] = None
        self._cam_pivot: Optional[Entity] = None
        self._rain:     List[Dict]    = []
        self._npcs:     List[Dict]    = []
        self._vehicles: List[Dict]    = []
        self._shards:   List[Dict]    = []
        self._beacons:  Dict[str, Dict] = {}    # task_id → beacon entities
        self._terminals: List[Dict]    = []
        self._neon_signs: List[Dict]   = []      # for flicker animation
        self._win_strips: List[Entity] = []      # building window strips
        self._stars:    List[Entity]   = []
        self._moon:     Optional[Entity] = None
        self._lightning_timer = 0.0
        self._lightning_flash: Optional[Entity] = None

        # ── HUD refs ─────────────────────────────────────────────────────
        self._hud_mission:   Optional[Text] = None
        self._hud_status:    Optional[Text] = None
        self._hud_xp:        Optional[Text] = None
        self._hud_cash:      Optional[Text] = None
        self._hud_stars:     Optional[Text] = None
        self._hud_interact:  Optional[Text] = None
        self._hud_level_up:  Optional[Text] = None
        self._hud_notify:    Optional[Text] = None
        self._notify_timer   = 0.0
        self._level_up_timer = 0.0
        self._minimap_bg:    Optional[Entity] = None
        self._minimap_dots:  Dict[str, Entity] = {}
        self._show_minimap   = True
        self._show_tasks     = True
        self._interact_target: Optional[Dict] = None
        self._frame_t = 0.0

        if not URSINA_OK:
            logger.warning("Ursina not installed — NovaMindscape is a stub.")

    # ── Thread-safe task API ─────────────────────────────────────────────────

    def update_tasks(self, tasks: List[Dict]):
        with self._lock:
           if self._hud_mission: self._hud_mission.text = "\n".join(texts)

    def _on_task_submit(self):
        text = self._task_input.text.strip()
        q = getattr(self, "_evt_queue", None)
        if text and q:
            q.put({"type": "task", "text": text})
        self._task_input.text = ""
        self._task_input.active = False
        self._task_input.visible = False

    def update_tasks(self, tasks: List[Dict]):
        self.update_tasks(tasks)

    def notify_task_complete(self, task: Dict):
        status = task.get("status", "done")
        xp_gain = 120 if status in ("success", "done") else 20
        self._xp   += xp_gain
        self._cash += (500 if status in ("success", "done") else 50)
        old_level = self._level
        self._level = 1 + self._xp // 200
        if self._level > old_level and self._hud_level_up:
            self._hud_level_up.text    = f"  LEVEL UP!  Agent Lvl {self._level}  "
            self._hud_level_up.visible = True
            self._level_up_timer = 4.0
        self._push_notify(
            f"+{xp_gain} XP  ·  +${500 if status in ('success','done') else 50}"
        )

    def _push_notify(self, msg: str):
        if self._hud_notify:
            self._hud_notify.text    = msg
            self._hud_notify.visible = True
            self._notify_timer = 3.5

    # ── Entry point ──────────────────────────────────────────────────────────

    def run(self):
        """
        Initialises the Ursina engine.
        In NovaMind v3, this is called on the main thread but DOES NOT block.
        The event loop is driven by the PyQt6 timer calling self.step().
        """
        if not URSINA_OK:
            logger.warning("Cannot run — install ursina: pip install ursina")
            return

        self._running = True
        self.app = Ursina(
            title=self.config.title,
            fullscreen=self.config.fullscreen,
            vsync=self.config.vsync,
            development_mode=self.config.dev_mode,
        )
        window.size = self.config.window_size
        window.fps_counter.enabled = True
        window.exit_button.visible = False
        mouse.locked  = True
        mouse.visible = False

        self._build_scene(self.app)
        logger.info("Ursina engine initialised (non-blocking).")

    def step(self):
        """Updates the game state by one frame. Called by the Qt main loop."""
        if self._running and URSINA_OK:
            try:
                # Correct way to step Ursina from external loop
                application.step()
            except Exception as exc:
                logger.debug(f"Game step error: {exc}")


    def stop(self):
        self._running = False
        if URSINA_OK:
            try:
                application.quit()
            except Exception:
                pass

    def run_blocking(self) -> None:
        """
        Blocking entry point for GameProcessManager child process.
        Calls app.run() which blocks until the window is closed.
        This is the correct way to run Ursina — NOT via an external step() loop.
        Zero if-elif — availability guard via O(1) dict lookup.
        """
        _unavail = {True: lambda: logger.warning(
            "run_blocking: ursina not installed — cannot start game"
        )}
        unavail = _unavail.get(not URSINA_OK)
        if unavail:
            unavail()
            return

        self._running = True
        app = Ursina(
            title=self.config.title,
            fullscreen=self.config.fullscreen,
            vsync=self.config.vsync,
            development_mode=self.config.dev_mode,
        )
        self._app = app

        # Apply performance overrides from config.py
        try:
            from config import GAME_RESOLUTION, GAME_LOW_PERF_MODE, GAME_RAIN_COUNT, GAME_NPC_COUNT, GAME_VEHICLE_COUNT
            window.size = GAME_RESOLUTION
            if GAME_LOW_PERF_MODE:
                self.config.rain_count    = 0              # biggest GPU saving
                self.config.npc_count     = GAME_NPC_COUNT
                self.config.vehicle_count = GAME_VEHICLE_COUNT
                logger.info("Low-perf mode active: rain disabled, reduced NPC/vehicle counts")
            else:
                window.size = GAME_RESOLUTION
        except Exception:
            window.size = self.config.window_size

        window.fps_counter.enabled = True
        window.exit_button.visible = False
        mouse.locked  = True
        mouse.visible = False

        try:
            self._build_scene(app)
            logger.info("Scene built successfully - entering app.run()")
        except Exception as e:
            logger.error(f"SCENE BUILD FAILED: {e}", exc_info=True)
            return

        if not hasattr(self, "_updater_entity"):
            self._updater_entity = Entity(eternal=True)
        self._updater_entity.update = self._game_update
        self._updater_entity.input = self._game_input

        logger.info("Nova Mindscape: run_blocking() — entering Ursina main loop")
        app.run()

    # ── Scene Construction ───────────────────────────────────────────────────

    def _build_scene(self, app):
        self._setup_sky()
        self._setup_lighting()
        self._build_terrain()
        self._build_roads()
        self._build_buildings()
        self._build_ai_tower()
        self._build_elevated_highway()
        self._build_monorail()
        self._build_street_details()
        if self.config.enable_rain:
            self._spawn_rain()
        if self.config.enable_npcs:
            self._spawn_pedestrians()
        if self.config.enable_traffic:
            self._spawn_vehicles()
        self._spawn_data_shards()
        self._build_hud()
        self._build_minimap()
        self._setup_player()
        self._cinematic_intro()

        app.update = self._game_update
        app.input  = self._game_input

    # ── Sky ──────────────────────────────────────────────────────────────────

    def _setup_sky(self):
        sky = Sky()
        sky.color = color.rgba(3, 4, 14, 255)

        # Star field
        rng = random.Random(11)
        for _ in range(180):
            px = rng.uniform(-180, 180)
            py = rng.uniform(40, 120)
            pz = rng.uniform(-180, 180)
            sz = rng.uniform(0.08, 0.25)
            br = rng.randint(180, 255)
            star = Entity(
                model="sphere",
                position=Vec3(px, py, pz),
                scale=sz,
                color=color.rgba(br, br, min(255, br + 20), rng.randint(160, 240)),
            )
            self._stars.append(star)

        # Moon
        self._moon = Entity(
            model="sphere",
            position=Vec3(80, 90, 160),
            scale=6.0,
            color=color.rgba(230, 240, 255, 245),
        )
        # Moon glow halo
        Entity(
            model="sphere",
            position=Vec3(80, 90, 160),
            scale=10.0,
            color=color.rgba(180, 210, 255, 35),
        )

        # Distant mountains / skyline silhouette
        rng2 = random.Random(55)
        for angle_step in range(24):
            angle = math.radians(angle_step * 15)
            dist  = 170
            mx = math.cos(angle) * dist
            mz = math.sin(angle) * dist
            mh = rng2.uniform(20, 55)
            mw = rng2.uniform(18, 40)
            Entity(
                model="cube",
                position=Vec3(mx, mh / 2, mz),
                scale=Vec3(mw, mh, rng2.uniform(8, 20)),
                color=color.rgba(5, 8, 18, 255),
            )

        # Cloud/smog planes
        for ci in range(6):
            cloud_col = color.rgba(15, 20, 40, rng2.randint(15, 35))
            Entity(
                model="quad",
                position=Vec3(rng2.uniform(-50, 50), rng2.uniform(35, 60),
                              rng2.uniform(-50, 50)),
                scale=Vec3(rng2.uniform(60, 100), rng2.uniform(12, 25), 1),
                color=cloud_col,
            )

    # ── Lighting ─────────────────────────────────────────────────────────────

    def _setup_lighting(self):
        if not URSINA_LIGHTS:
            return
        ambient = AmbientLight()
        ambient.color = color.rgba(12, 18, 45, 255)

        sun = DirectionalLight()
        sun.look_at(Vec3(-1, -3, -1))
        sun.color = color.rgba(20, 30, 70, 255)

        # Neon district lights — one per road intersection
        neon_palette = [
            (0, 212, 255, 180),  # cyan
            (255,  50, 150, 150), # magenta
            (100, 255, 100, 130), # green
            (255, 180,   0, 150), # amber
            (140,  80, 255, 140), # purple
        ]
        rng = random.Random(42)
        for rx in _RCENTRES:
            for rz in _RCENTRES:
                cr, cg, cb, ca = rng.choice(neon_palette)
                pl = PointLight()
                pl.position = Vec3(rx, 8, rz)
                pl.color    = color.rgba(cr, cg, cb, ca)

    # ── Terrain ──────────────────────────────────────────────────────────────

    def _build_terrain(self):
        # Main ground — dark wet asphalt look
        Entity(
            model="plane", scale=260,
            color=color.rgba(5, 7, 16, 255),
        )
        # Waterfront canal along the south edge
        Entity(
            model="cube",
            position=Vec3(0, -0.25, -115),
            scale=Vec3(220, 0.5, 22),
            color=color.rgba(0, 30, 60, 240),
        )
        # Water shimmer strips
        rng = random.Random(7)
        for i in range(18):
            Entity(
                model="cube",
                position=Vec3(rng.uniform(-100, 100), 0.02, -115 + rng.uniform(-9, 9)),
                scale=Vec3(rng.uniform(4, 20), 0.01, 0.15),
                color=color.rgba(0, 100, 200, rng.randint(40, 90)),
            )
        # Canal bridge
        Entity(
            model="cube",
            position=Vec3(0, 0.15, -105),
            scale=Vec3(18, 0.3, 22),
            color=color.rgba(18, 22, 40, 255),
        )
        for bx in [-7, 7]:
            Entity(
                model="cube",
                position=Vec3(bx, 1.5, -105),
                scale=Vec3(0.4, 3.0, 22),
                color=color.rgba(0, 180, 255, 180),
            )

    # ── Roads ────────────────────────────────────────────────────────────────

    def _build_roads(self):
        rng = random.Random(21)
        city_half = 115

        # Road surface quads (E-W and N-S roads)
        for rc in _RCENTRES:
            # E-W road
            Entity(
                model="cube",
                position=Vec3(0, 0.04, rc),
                scale=Vec3(city_half * 2, 0.08, ROAD_W),
                color=color.rgba(10, 11, 18, 255),
            )
            # N-S road
            Entity(
                model="cube",
                position=Vec3(rc, 0.04, 0),
                scale=Vec3(ROAD_W, 0.08, city_half * 2),
                color=color.rgba(10, 11, 18, 255),
            )
            # Centre line (dashes)
            for seg in range(-14, 15):
                if abs(seg) % 2 == 0:
                    Entity(
                        model="cube",
                        position=Vec3(seg * 8, 0.06, rc),
                        scale=Vec3(4.5, 0.04, 0.15),
                        color=color.rgba(60, 65, 50, 180),
                    )
                    Entity(
                        model="cube",
                        position=Vec3(rc, 0.06, seg * 8),
                        scale=Vec3(0.15, 0.04, 4.5),
                        color=color.rgba(60, 65, 50, 180),
                    )

        # Sidewalks along roads
        sw_offset = ROAD_W / 2 + 1.2
        sw_col = color.rgba(16, 18, 28, 255)
        for bc in _BCENTRES:
            for rc in _RCENTRES:
                # Sidewalk strip beside E-W road on each block
                Entity(
                    model="cube",
                    position=Vec3(bc, 0.06, rc + sw_offset),
                    scale=Vec3(BLOCK_SIZE - 2, 0.12, 2.2),
                    color=sw_col,
                )
                Entity(
                    model="cube",
                    position=Vec3(bc, 0.06, rc - sw_offset),
                    scale=Vec3(BLOCK_SIZE - 2, 0.12, 2.2),
                    color=sw_col,
                )
                Entity(
                    model="cube",
                    position=Vec3(rc + sw_offset, 0.06, bc),
                    scale=Vec3(2.2, 0.12, BLOCK_SIZE - 2),
                    color=sw_col,
                )
                Entity(
                    model="cube",
                    position=Vec3(rc - sw_offset, 0.06, bc),
                    scale=Vec3(2.2, 0.12, BLOCK_SIZE - 2),
                    color=sw_col,
                )

        # Intersection crossing blocks (coloured)
        for rx in _RCENTRES:
            for rz in _RCENTRES:
                Entity(
                    model="cube",
                    position=Vec3(rx, 0.05, rz),
                    scale=Vec3(ROAD_W, 0.09, ROAD_W),
                    color=color.rgba(12, 13, 22, 255),
                )
                # Crosswalk stripes
                for s in range(-5, 6, 2):
                    Entity(
                        model="cube",
                        position=Vec3(rx + s * 0.9, 0.065, rz),
                        scale=Vec3(0.55, 0.04, ROAD_W),
                        color=color.rgba(35, 38, 55, 200),
                    )

        # Traffic light poles at each intersection
        for rx in _RCENTRES:
            for rz in _RCENTRES:
                for ox, oz in [(ROAD_W / 2 + 0.5, ROAD_W / 2 + 0.5),
                               (-ROAD_W / 2 - 0.5, -ROAD_W / 2 - 0.5)]:
                    px, pz = rx + ox, rz + oz
                    Entity(model="cube", position=Vec3(px, 2.5, pz),
                           scale=Vec3(0.12, 5.0, 0.12),
                           color=color.rgba(30, 32, 40, 255))
                    # Light head
                    gc = rng.choice([(0, 220, 80), (255, 200, 0), (220, 40, 40)])
                    Entity(model="cube", position=Vec3(px, 5.2, pz),
                           scale=Vec3(0.35, 0.7, 0.2),
                           color=color.rgba(*gc, 220))

    # ── Buildings ────────────────────────────────────────────────────────────

    def _build_buildings(self):
        rng = random.Random(33)
        dist_from_centre = lambda bx, bz: math.hypot(bx, bz)

        btype_by_dist = {
            "near":   ["tower", "tower", "corporate", "hotel"],
            "mid":    ["apartment", "hotel", "club", "corporate"],
            "far":    ["warehouse", "club", "apartment", "industrial"],
        }

        for bx in _BCENTRES:
            for bz in _BCENTRES:
                d = dist_from_centre(bx, bz)
                band = "near" if d < 50 else ("mid" if d < 85 else "far")
                btype = rng.choice(btype_by_dist[band])
                n_buildings = rng.randint(1, 3) if band == "far" else 1
                self._place_building_cluster(bx, bz, btype, n_buildings, rng)

    def _place_building_cluster(self, bx: float, bz: float,
                                 btype: str, count: int,
                                 rng: random.Random):
        specs = {
            "tower":      (rng.uniform(28, 58), rng.uniform(8, 13),  rng.uniform(8, 13),  (7, 12, 28)),
            "corporate":  (rng.uniform(20, 35), rng.uniform(10, 16), rng.uniform(10, 16), (9, 15, 32)),
            "hotel":      (rng.uniform(16, 28), rng.uniform(9, 14),  rng.uniform(9, 14),  (12, 16, 30)),
            "apartment":  (rng.uniform(12, 22), rng.uniform(8, 12),  rng.uniform(8, 12),  (10, 14, 25)),
            "club":       (rng.uniform(6, 12),  rng.uniform(12, 18), rng.uniform(10, 16), (22, 6, 28)),
            "warehouse":  (rng.uniform(5, 9),   rng.uniform(14, 22), rng.uniform(14, 22), (14, 14, 16)),
            "industrial": (rng.uniform(7, 13),  rng.uniform(12, 20), rng.uniform(12, 20), (12, 12, 14)),
        }
        bh, bw, bd, base_col = specs.get(btype, specs["apartment"])
        br, bg, bb = base_col

        # O(1) offset selection via list-multiply trick — zero if/else branching
        # list * True(1) = list,  list * False(0) = [] → 'or' falls to cluster
        half     = BLOCK_SIZE / 2 - bw / 2 - 1
        _single  = [(0.0, 0.0, 1.0, 1.0, 1.0)]          # (ox, oz, hs, ws, ds)
        _cluster = [(-half, -half, None, None, None),
                    ( half, -half, None, None, None),
                    (-half,  half, None, None, None),
                    ( half,  half, None, None, None)]
        offsets = (_single * (count == 1)) or _cluster[:max(count, 1)]
        for ox, oz, hs, ws, ds in offsets:
            h2 = bh * (hs or rng.uniform(0.5, 0.85))
            w2 = bw * (ws or rng.uniform(0.7, 0.9))
            d2 = bd * (ds or rng.uniform(0.7, 0.9))
            self._make_building(bx + ox, bz + oz, h2, w2, d2, br, bg, bb, btype, rng)

    def _make_building(self, bx: float, bz: float,
                       bh: float, bw: float, bd: float,
                       br: int, bg: int, bb: int,
                       btype: str, rng: random.Random):
        # ── Main body ──────────────────────────────────────────────────
        Entity(
            model="cube",
            position=Vec3(bx, bh / 2, bz),
            scale=Vec3(bw, bh, bd),
            color=color.rgba(br, bg, bb, 255),
        )

        # ── Setback upper section (corporate/tower tapers) ──────────────
        if btype in ("tower", "corporate") and bh > 22:
            mid_h = bh * 0.55
            Entity(
                model="cube",
                position=Vec3(bx, bh * 0.78, bz),
                scale=Vec3(bw * 0.75, bh * 0.45, bd * 0.75),
                color=color.rgba(max(0, br - 5), max(0, bg - 5), min(255, bb + 8), 255),
            )

        # ── Window strips (front + back) ────────────────────────────────
        floor_h = 3.0
        n_floors = int(bh / floor_h)
        wc = (rng.randint(140, 220), rng.randint(150, 220), rng.randint(180, 255))
        for f in range(1, n_floors):
            wy = f * floor_h + 0.3
            wa = rng.randint(80, 200)
            strip_f = Entity(
                model="cube",
                position=Vec3(bx, wy, bz - bd / 2 - 0.02),
                scale=Vec3(bw - 0.8, 0.6, 0.08),
                color=color.rgba(*wc, wa),
            )
            strip_b = Entity(
                model="cube",
                position=Vec3(bx, wy, bz + bd / 2 + 0.02),
                scale=Vec3(bw - 0.8, 0.6, 0.08),
                color=color.rgba(*wc, rng.randint(60, 180)),
            )
            self._win_strips.extend([strip_f, strip_b])

        # ── Rooftop neon edge ────────────────────────────────────────────
        nc = rng.choice([
            (0, 212, 255), (255, 50, 150), (100, 255, 100),
            (255, 180, 0), (160, 100, 255),
        ])
        Entity(
            model="cube",
            position=Vec3(bx, bh + 0.08, bz),
            scale=Vec3(bw + 0.15, 0.15, bd + 0.15),
            color=color.rgba(*nc, 230),
        )

        # ── Antenna / rooftop features ──────────────────────────────────
        if btype in ("tower", "corporate") and bh > 20:
            Entity(
                model="cube",
                position=Vec3(bx, bh + 5, bz),
                scale=Vec3(0.1, 10, 0.1),
                color=color.rgba(80, 80, 90, 255),
            )
            Entity(
                model="sphere",
                position=Vec3(bx, bh + 10.3, bz),
                scale=0.28,
                color=color.rgba(255, 60, 60, 240),
            )
            # Blinking light via spawn (just visible entity; blink in update)
            blink = Entity(
                model="sphere",
                position=Vec3(bx, bh + 10.3, bz),
                scale=0.5,
                color=color.rgba(255, 80, 80, 100),
            )
            blink._blink_phase = rng.uniform(0, 6.28)
            self._neon_signs.append({"type": "blink", "ent": blink,
                                     "phase": rng.uniform(0, 6.28),
                                     "rgb": (255, 60, 60)})

        # Warehouse chimneys — frozenset O(1) membership + list-comprehension side effect
        btype in frozenset({"warehouse"}) and [
            Entity(model="cube",
                   position=Vec3(bx + cx, bh + 2.5, bz),
                   scale=Vec3(0.8, 5, 0.8),
                   color=color.rgba(25, 22, 20, 255))
            for cx in (-bw / 4, bw / 4)
        ]

        # ── Neon wall sign ───────────────────────────────────────────────
        if rng.random() < 0.55:
            sign_texts = [
                "NOVA NET", "CYBER CORP", "NEON DINER", "HACK CLUB",
                "DIGITAL", "OVERDRIVE", "MATRIX", "GHOST NET",
                "CHROME", "NIGHT OWL", "DARK DATA", "PULSE CITY",
                "AI CORE", "SYN LABS", "NOVA TECH", "NEON WAVE",
            ]
            sc = rng.choice([(0, 212, 255), (255, 50, 150), (100, 255, 100),
                             (255, 200, 0), (180, 100, 255)])
            sign_ent = Text(
                text=rng.choice(sign_texts),
                position=Vec3(bx, rng.uniform(bh * 0.3, bh * 0.7), bz - bd / 2 - 0.3),
                scale=5.5,
                color=color.rgba(*sc, 245),
                billboard=False,
            )
            # Glow backing quad
            glow_q = Entity(
                model="quad",
                position=Vec3(bx, rng.uniform(bh * 0.3, bh * 0.7), bz - bd / 2 - 0.4),
                scale=Vec3(bw * 0.6, 1.2, 1),
                color=color.rgba(*sc, 35),
            )
            self._neon_signs.append({"type": "sign", "ent": glow_q,
                                     "phase": rng.uniform(0, 6.28),
                                     "rgb": sc})

    # ── Central AI Tower ─────────────────────────────────────────────────────

    def _build_ai_tower(self):
        """The NovaMind HQ — tallest structure, centrepiece of the city."""
        # Base platform
        Entity(
            model="cube",
            position=Vec3(0, 0.3, 0),
            scale=Vec3(28, 0.6, 28),
            color=color.rgba(8, 12, 30, 255),
        )
        # Plaza ring
        Entity(
            model="cube",
            position=Vec3(0, 0.5, 0),
            scale=Vec3(22, 0.4, 22),
            color=color.rgba(14, 20, 48, 255),
        )

        # Tower core — 4 sections tapering upward
        for i, (hy, hw, hc) in enumerate([
            (35,  12,  (8,  14, 38)),
            (62,   9,  (6,  12, 45)),
            (74,   6,  (5,  10, 55)),
            (82,   4,  (4,   8, 60)),
        ]):
            Entity(
                model="cube",
                position=Vec3(0, hy / 2, 0),
                scale=Vec3(hw, hy, hw),
                color=color.rgba(*hc, 255),
            )

        # Glowing vertical strips on tower
        for angle_deg in range(0, 360, 90):
            a = math.radians(angle_deg)
            sx = math.sin(a) * 6.05
            sz = math.cos(a) * 6.05
            Entity(
                model="cube",
                position=Vec3(sx, 42, sz),
                scale=Vec3(0.15, 84, 0.15),
                color=color.rgba(0, 212, 255, 80),
            )

        # Window strips on tower
        for floor in range(3, 78, 4):
            for angle_deg in range(0, 360, 90):
                a = math.radians(angle_deg)
                side = max(1, 12 - floor // 10)
                sx = math.sin(a) * (side / 2 + 0.08)
                sz = math.cos(a) * (side / 2 + 0.08)
                Entity(
                    model="cube",
                    position=Vec3(sx, floor, sz),
                    scale=Vec3(0.08, 0.5, side),
                    color=color.rgba(100, 200, 255, 120),
                )

        # Observation deck crown
        Entity(
            model="cube",
            position=Vec3(0, 86, 0),
            scale=Vec3(7, 1.2, 7),
            color=color.rgba(0, 180, 255, 200),
        )

        # Crown sphere — the AI orb
        for i, (rs, ra) in enumerate([(5.0, 210), (3.8, 180), (2.5, 240)]):
            Entity(
                model="sphere",
                position=Vec3(0, 90, 0),
                scale=rs,
                color=color.rgba(0, 212, 255, ra),
            )

        # Rotating rings around AI orb
        for ri, (rx_scale, col_a) in enumerate([
            (Vec3(7.5, 0.12, 7.5), color.rgba(0, 212, 255, 170)),
            (Vec3(6.0, 0.12, 6.0), color.rgba(140, 80, 255, 140)),
        ]):
            Entity(
                model="sphere",
                position=Vec3(0, 90, 0),
                scale=rx_scale,
                color=col_a,
            )

        # NOVAMIND text on tower
        Text(
            text="NOVAMIND",
            position=Vec3(0, 55, -7.5),
            scale=9,
            color=color.rgba(0, 212, 255, 255),
            billboard=False,
        )
        Text(
            text="AI CORE",
            position=Vec3(0, 50, -7.5),
            scale=6.5,
            color=color.rgba(180, 200, 255, 200),
            billboard=False,
        )

        # Vertical light shafts
        for angle_deg in range(0, 360, 45):
            a  = math.radians(angle_deg)
            lx = math.sin(a) * 10
            lz = math.cos(a) * 10
            Entity(
                model="cube",
                position=Vec3(lx, 50, lz),
                scale=Vec3(0.06, 100, 0.06),
                color=color.rgba(0, 212, 255, 25),
            )

    # ── Elevated Highway ─────────────────────────────────────────────────────

    def _build_elevated_highway(self):
        hw_y = 16.0
        # E-W highway across city
        Entity(
            model="cube",
            position=Vec3(0, hw_y, 38),
            scale=Vec3(220, 0.5, 12),
            color=color.rgba(20, 22, 35, 255),
        )
        # Guard rails
        for side in [-1, 1]:
            Entity(
                model="cube",
                position=Vec3(0, hw_y + 0.5, 38 + side * 6.2),
                scale=Vec3(220, 1.0, 0.25),
                color=color.rgba(0, 160, 255, 160),
            )
        # Support pillars
        for px in range(-100, 110, 25):
            Entity(
                model="cube",
                position=Vec3(px, hw_y / 2, 38),
                scale=Vec3(1.4, hw_y, 1.4),
                color=color.rgba(18, 20, 35, 255),
            )
        # N-S highway
        Entity(
            model="cube",
            position=Vec3(-38, hw_y + 0.05, 0),
            scale=Vec3(12, 0.5, 220),
            color=color.rgba(20, 22, 35, 255),
        )
        for side in [-1, 1]:
            Entity(
                model="cube",
                position=Vec3(-38 + side * 6.2, hw_y + 0.55, 0),
                scale=Vec3(0.25, 1.0, 220),
                color=color.rgba(255, 120, 0, 160),
            )
        for pz in range(-100, 110, 25):
            Entity(
                model="cube",
                position=Vec3(-38, hw_y / 2, pz),
                scale=Vec3(1.4, hw_y, 1.4),
                color=color.rgba(18, 20, 35, 255),
            )

    # ── Monorail ─────────────────────────────────────────────────────────────

    def _build_monorail(self):
        rail_y = 23.0
        Entity(
            model="cube",
            position=Vec3(0, rail_y, 0),
            scale=Vec3(220, 0.35, 1.8),
            color=color.rgba(30, 35, 55, 255),
        )
        Entity(
            model="cube",
            position=Vec3(0, rail_y - 0.45, 0),
            scale=Vec3(220, 0.15, 0.4),
            color=color.rgba(0, 212, 255, 120),
        )
        # Monorail train entity (moves in update)
        self._monorail_train = Entity(
            model="cube",
            position=Vec3(-100, rail_y + 0.65, 0),
            scale=Vec3(16, 2.2, 2.8),
            color=color.rgba(10, 14, 32, 255),
        )
        # Train windows
        for wx in range(-6, 8, 3):
            Entity(
                model="cube",
                position=Vec3(wx, 0.4, -1.42),
                scale=Vec3(1.8, 0.6, 0.08),
                color=color.rgba(120, 200, 255, 160),
                parent=self._monorail_train,
            )
        # Support pillars
        for px in range(-100, 110, 30):
            Entity(
                model="cube",
                position=Vec3(px, rail_y / 2 + 1, 0),
                scale=Vec3(0.6, rail_y, 0.6),
                color=color.rgba(20, 22, 40, 255),
            )

    # ── Street Details ────────────────────────────────────────────────────────

    def _build_street_details(self):
        rng = random.Random(66)
        # Lampposts on sidewalks
        for rc in _RCENTRES:
            for bc in _BCENTRES:
                for sx, sz in [(ROAD_W / 2 + 2.3, 0), (-ROAD_W / 2 - 2.3, 0),
                               (0, ROAD_W / 2 + 2.3), (0, -ROAD_W / 2 - 2.3)]:
                    lx = bc + sx if sx != 0 else rc
                    lz = bc + sz if sz != 0 else rc
                    if sx == 0:
                        lx, lz = lx, bc + BLOCK_SIZE / 2 * rng.choice([-1, 1])
                    # Post
                    Entity(
                        model="cube",
                        position=Vec3(lx, 2.5, lz),
                        scale=Vec3(0.12, 5.0, 0.12),
                        color=color.rgba(25, 28, 40, 255),
                    )
                    # Head
                    Entity(
                        model="cube",
                        position=Vec3(lx, 5.2, lz),
                        scale=Vec3(0.7, 0.25, 0.25),
                        color=color.rgba(0, 212, 255, 200),
                    )
                    # Glow sphere
                    Entity(
                        model="sphere",
                        position=Vec3(lx, 5.35, lz),
                        scale=0.35,
                        color=color.rgba(150, 230, 255, 180),
                    )

        # Data terminals — interactive objects with tasks
        terminal_positions = [
            (0, -8), (0, 8), (-8, 0), (8, 0),
            (38, 38), (-38, 38), (38, -38), (-38, -38),
            (19, 0), (-19, 0), (0, 19), (0, -19),
        ]
        for i, (tx, tz) in enumerate(terminal_positions):
            # Terminal body
            t_body = Entity(
                model="cube",
                position=Vec3(tx, 0.8, tz),
                scale=Vec3(0.6, 1.6, 0.35),
                color=color.rgba(10, 14, 30, 255),
                collider="box",
            )
            # Screen
            t_screen = Entity(
                model="quad",
                position=Vec3(tx, 1.0, tz - 0.19),
                scale=Vec3(0.45, 0.7, 1),
                color=color.rgba(0, 180, 255, 180),
            )
            # Screen glow
            t_glow = Entity(
                model="quad",
                position=Vec3(tx, 1.0, tz - 0.22),
                scale=Vec3(0.65, 0.9, 1),
                color=color.rgba(0, 180, 255, 40),
            )
            # Label
            Text(
                text="NOVAMIND\nTERMINAL",
                position=Vec3(tx, 2.0, tz - 0.2),
                scale=2.8,
                color=color.rgba(0, 212, 255, 220),
                billboard=False,
            )
            self._terminals.append({
                "body": t_body, "screen": t_screen, "glow": t_glow,
                "pos": Vec3(tx, 0, tz), "index": i,
            })
            self._neon_signs.append({
                "type": "terminal",
                "ent": t_glow,
                "phase": rng.uniform(0, 6.28),
                "rgb": (0, 180, 255),
            })

        # Parked cars
        for i in range(20):
            px = rng.choice(_BCENTRES) + rng.uniform(-8, 8)
            pz = rng.choice(_RCENTRES) + ROAD_W / 2 + 2.5
            pc = rng.choice([(15, 18, 35), (8, 10, 20), (25, 10, 30), (10, 20, 15)])
            Entity(model="cube", position=Vec3(px, 0.5, pz),
                   scale=Vec3(2.2, 0.85, 4.2), color=color.rgba(*pc, 255))
            Entity(model="cube", position=Vec3(px, 1.1, pz + 0.3),
                   scale=Vec3(1.8, 0.65, 2.0), color=color.rgba(*pc, 230))
            # Headlights
            for hx_off in [-0.7, 0.7]:
                Entity(model="cube", position=Vec3(px + hx_off, 0.6, pz - 2.1),
                       scale=Vec3(0.3, 0.15, 0.06),
                       color=color.rgba(220, 220, 180, 200))

        # Dumpsters / props
        for _ in range(15):
            dpx = rng.choice(_BCENTRES) + rng.uniform(-10, 10)
            dpz = rng.choice(_BCENTRES) + rng.uniform(-10, 10)
            Entity(model="cube", position=Vec3(dpx, 0.5, dpz),
                   scale=Vec3(1.0, 1.0, 1.6),
                   color=color.rgba(rng.randint(10, 35), rng.randint(35, 55),
                                    rng.randint(20, 40), 255))

    # ── Rain ─────────────────────────────────────────────────────────────────

    def _spawn_rain(self):
        rng = random.Random(88)
        for _ in range(self.config.rain_count):
            px = rng.uniform(-80, 80)
            pz = rng.uniform(-80, 80)
            py = rng.uniform(2, 35)
            ent = Entity(
                model="cube",
                position=Vec3(px, py, pz),
                scale=Vec3(0.018, 0.55, 0.018),
                rotation=Vec3(0, 0, 10),  # slight wind angle
                color=color.rgba(160, 200, 255, rng.randint(50, 100)),
            )
            self._rain.append({
                "ent": ent,
                "speed": rng.uniform(18, 30),
                "px": px, "pz": pz,
            })

    # ── Pedestrians ──────────────────────────────────────────────────────────

    def _spawn_pedestrians(self):
        rng = random.Random(44)
        npc_styles = [
            {"body_col": (0, 120, 200), "head_col": (220, 180, 140)},
            {"body_col": (200, 60, 120), "head_col": (200, 160, 120)},
            {"body_col": (40, 180, 100), "head_col": (230, 190, 150)},
            {"body_col": (160, 90, 210), "head_col": (200, 170, 130)},
            {"body_col": (220, 140, 30), "head_col": (190, 150, 110)},
        ]
        for i in range(self.config.npc_count):
            sx = rng.choice(_RCENTRES) + rng.choice([-ROAD_W / 2 - 2.5, ROAD_W / 2 + 2.5])
            sz = rng.uniform(-100, 100)
            style = rng.choice(npc_styles)
            body = Entity(
                model="cube",
                position=Vec3(sx, 0.7, sz),
                scale=Vec3(0.4, 1.4, 0.4),
                color=color.rgba(*style.get("body_col", (255, 255, 255)), 240),
            )
            head = Entity(
                model="sphere",
                position=Vec3(0, 0.9, 0),
                scale=Vec3(0.38, 0.38, 0.38),
                color=color.rgba(*style.get("head_col", (200, 200, 200)), 255),
                parent=body,
            )
            self._npcs.append({
                "body": body, "head": head,
                "walk_dir": Vec3(0, 0, rng.choice([-1, 1])),
                "speed": rng.uniform(1.5, 3.5),
                "bob_phase": rng.uniform(0, 6.28),
                "turnaround": sz + rng.choice([-1, 1]) * rng.uniform(15, 40),
            })

    # ── Traffic Vehicles ──────────────────────────────────────────────────────

    def _spawn_vehicles(self):
        rng = random.Random(77)
        road_configs = []
        for rc in _RCENTRES:
            road_configs.append({
                "waypoints": [Vec3(-108, 0.5, rc + 2.5), Vec3(108, 0.5, rc + 2.5)],
                "loop": True, "forward": True,
            })
            road_configs.append({
                "waypoints": [Vec3(108, 0.5, rc - 2.5), Vec3(-108, 0.5, rc - 2.5)],
                "loop": True, "forward": False,
            })
            road_configs.append({
                "waypoints": [Vec3(rc + 2.5, 0.5, -108), Vec3(rc + 2.5, 0.5, 108)],
                "loop": True, "forward": True,
            })

        car_styles = [
            {"body": (8, 12, 28), "roof": (5, 8, 20)},
            {"body": (28, 8, 14), "roof": (20, 5, 10)},
            {"body": (8, 25, 14), "roof": (5, 18, 10)},
            {"body": (25, 18, 8), "roof": (20, 14, 5)},
        ]
        for i in range(self.config.vehicle_count):
            rc_cfg = rng.choice(road_configs)
            wps    = rc_cfg["waypoints"]
            style  = rng.choice(car_styles)
            start  = Vec3(wps[0].x + rng.uniform(-50, 50),
                          wps[0].y, wps[0].z)
            body = Entity(
                model="cube",
                position=start,
                scale=Vec3(2.0, 0.75, 4.0),
                color=color.rgba(*style["body"], 255),
            )
            roof = Entity(
                model="cube",
                position=Vec3(0, 0.72, 0.1),
                scale=Vec3(0.85, 0.58, 0.6),
                color=color.rgba(*style["roof"], 240),
                parent=body,
            )
            # Headlights
            for hx_off in [-0.65, 0.65]:
                Entity(
                    model="cube",
                    position=Vec3(hx_off, -0.1, 2.05),
                    scale=Vec3(0.28, 0.14, 0.06),
                    color=color.rgba(240, 240, 200, 220),
                    parent=body,
                )
            # Tail lights
            for hx_off in [-0.65, 0.65]:
                Entity(
                    model="cube",
                    position=Vec3(hx_off, -0.1, -2.05),
                    scale=Vec3(0.28, 0.14, 0.06),
                    color=color.rgba(255, 30, 30, 200),
                    parent=body,
                )
            self._vehicles.append({
                "body": body, "waypoints": wps,
                "wp_idx": 0,
                "speed": rng.uniform(10, 22),
                "pos": Vec3(start.x, start.y, start.z),
            })

    # ── Data Shards (collectibles) ────────────────────────────────────────────

    def _spawn_data_shards(self):
        rng = random.Random(99)
        colours = [
            (0, 255, 150), (255, 220, 0), (200, 100, 255),
            (0, 200, 255), (255, 80, 200), (100, 255, 100),
        ]
        for _ in range(self.config.shard_count):
            sx = rng.uniform(-100, 100)
            sz = rng.uniform(-100, 100)
            if math.hypot(sx, sz) < 8:
                continue
            cr, cg, cb = rng.choice(colours)
            shard = Entity(
                model="cube",
                position=Vec3(sx, 0.5, sz),
                scale=Vec3(0.28, 0.55, 0.28),
                color=color.rgba(cr, cg, cb, 230),
                collider="box",
            )
            shard._rgb = (cr, cg, cb)
            self._shards.append({
                "ent": shard, "alive": True,
                "xp": rng.randint(15, 45),
                "respawn_at": 0.0,
                "orig": Vec3(sx, 0.5, sz),
            })

    # ── HUD ──────────────────────────────────────────────────────────────────

    def _build_hud(self):
        ui = camera.ui

        # ── Active mission (top-left, GTA style) ─────────────────────────
        self._hud_mission = Text(
            text=" ",
            position=Vec3(-0.87, 0.47),
            scale=0.85,
            color=color.rgba(255, 200, 50, 245),
            parent=ui,
        )
        self._hud_mission.wordwrap = 55
        self._hud_mission.text = ""

        # ── Agent stats (bottom-left) ─────────────────────────────────────
        self._hud_xp = Text(
            text="XP: 0  LVL: 1",
            position=Vec3(-0.87, -0.40),
            scale=0.88,
            color=color.rgba(0, 212, 255, 235),
            parent=ui,
        )
        self._hud_cash = Text(
            text="$0",
            position=Vec3(-0.87, -0.44),
            scale=0.82,
            color=color.rgba(50, 220, 80, 230),
            parent=ui,
        )

        # ── Star rating (bottom-left, GTA wanted) ─────────────────────────
        self._hud_stars = Text(
            text="★★★★★",
            position=Vec3(-0.87, -0.48),
            scale=0.88,
            color=color.rgba(255, 210, 0, 235),
            parent=ui,
        )

        # ── Status line (top-right) ───────────────────────────────────────
        self._hud_status = Text(
            text=" ",
            position=Vec3(0.25, 0.47),
            scale=0.78,
            color=color.rgba(180, 200, 230, 220),
            parent=ui,
        )
        self._hud_status.wordwrap = 52
        self._hud_status.text = ""

        #  In-game Task Input Field (hidden by default, toggle with Tab) 
        self._task_input = InputField(
            y=-0.45,
            scale=(0.8, 0.05),
            active=False,
            visible=False,
            parent=ui,
        )
        self._task_input.on_submit = self._on_task_submit

        self._hud_task_hint = Text(
            text="[TAB] ENTER TASK",
            position=Vec3(0, -0.48),
            scale=0.8,
            color=color.rgba(200, 200, 200, 180),
            origin=(0, 0),
            parent=ui,
        )

        # ── Interaction prompt (bottom-centre) ────────────────────────────
        self._hud_interact = Text(
            text="",
            position=Vec3(0, -0.40),
            scale=0.90,
            color=color.rgba(255, 255, 100, 240),
            origin=(0, 0),
            parent=ui,
        )

        # ── Level up banner (centre) ──────────────────────────────────────
        self._hud_level_up = Text(
            text="",
            position=Vec3(0, 0.12),
            scale=1.6,
            color=color.rgba(255, 220, 0, 250),
            origin=(0, 0),
            parent=ui,
        )
        self._hud_level_up.visible = False

        # ── Notification popup (centre-top) ───────────────────────────────
        self._hud_notify = Text(
            text="",
            position=Vec3(0, 0.36),
            scale=0.9,
            color=color.rgba(0, 212, 255, 240),
            origin=(0, 0),
            parent=ui,
        )
        self._hud_notify.visible = False

        # ── Crosshair ─────────────────────────────────────────────────────
        self._crosshair = Text(
            text="·",
            position=Vec3(0, 0),
            scale=2.5,
            color=color.rgba(0, 212, 255, 180),
            origin=(0, 0),
            parent=ui,
        )

        # ── Scan-line overlay ─────────────────────────────────────────────
        try:
            Entity(
                model="quad",
                scale=Vec3(2, 2, 1),
                color=color.rgba(0, 0, 0, 12),
                parent=ui,
            )
        except Exception:
            pass

        # ── Controls hint ─────────────────────────────────────────────────
        Text(
            text="WASD:move  Shift:sprint  Space:jump  F:interact  V:cam  M:map  T:tasks  ESC:quit",
            position=Vec3(-0.87, -0.47),
            scale=0.55,
            color=color.rgba(50, 65, 100, 180),
            parent=ui,
        )

        # ── Lightning flash overlay ────────────────────────────────────────
        self._lightning_flash = Entity(
            model="quad",
            scale=Vec3(3, 3, 1),
            color=color.rgba(220, 230, 255, 0),
            parent=ui,
        )

    # ── Minimap ───────────────────────────────────────────────────────────────

    def _build_minimap(self):
        ui = camera.ui
        # Background plate
        self._minimap_bg = Entity(
            model="quad",
            position=Vec3(0.80, -0.37),
            scale=Vec3(0.26, 0.30, 1),
            color=color.rgba(4, 7, 18, 210),
            parent=ui,
        )
        # Border
        Entity(
            model="quad",
            position=Vec3(0.80, -0.37),
            scale=Vec3(0.27, 0.31, 1),
            color=color.rgba(0, 212, 255, 100),
            parent=ui,
        )
        # Player dot (white triangle — represented as small square)
        self._mm_player = Entity(
            model="quad",
            position=Vec3(0.80, -0.37),
            scale=Vec3(0.007, 0.009, 1),
            color=color.rgba(255, 255, 255, 255),
            parent=ui,
        )
        Text(
            text="MAP",
            position=Vec3(0.70, -0.244),
            scale=0.42,
            color=color.rgba(0, 212, 255, 140),
            parent=ui,
        )
        # Compass labels
        for lbl, ox, oy in [("N", 0, 0.12), ("S", 0, -0.12),
                             ("E", 0.115, 0), ("W", -0.115, 0)]:
            Text(
                text=lbl,
                position=Vec3(0.80 + ox, -0.37 + oy),
                scale=0.32,
                color=color.rgba(80, 100, 140, 160),
                origin=(0, 0),
                parent=ui,
            )

    # ── Player setup ─────────────────────────────────────────────────────────

    def _setup_player(self):
        # Visible player body
        self._player = Entity(
            model="cube",
            position=Vec3(0, 0.85, -20),
            scale=Vec3(0.65, 1.65, 0.65),
            color=color.rgba(0, 180, 255, 230),
        )
        # Head
        Entity(
            model="sphere",
            position=Vec3(0, 0.6, 0),
            scale=Vec3(0.48, 0.48, 0.48),
            color=color.rgba(200, 220, 255, 250),
            parent=self._player,
        )
        # Shoulder visor glow
        Entity(
            model="cube",
            position=Vec3(0, 0.35, -0.36),
            scale=Vec3(0.66, 0.12, 0.08),
            color=color.rgba(0, 212, 255, 180),
            parent=self._player,
        )

        # Camera pivot parented to player
        self._cam_pivot = Entity(
            parent=self._player,
            position=Vec3(0, 0.6, 0),
        )
        self._apply_camera_mode()

    def _apply_camera_mode(self):
        if not self._cam_pivot:
            return
        camera.parent = self._cam_pivot
        # O(1) dict dispatch — zero if/else branching
        cfg = _CAM_MODE_SETTINGS[self._third_person]
        camera.position = Vec3(*cfg["cam_pos"])
        camera.rotation = Vec3(*cfg["cam_rot"])
        self._player and setattr(self._player, "visible", cfg["player_vis"])
        camera.fov = self.config.fov

    # ── Cinematic intro ───────────────────────────────────────────────────────

    def _cinematic_intro(self):
        """Brief top-down sweep into the city, then hands control to player."""
        # Skipping invoke() animation because it crashes before app.run() starts
        camera.parent   = self._cam_pivot
        camera.position = Vec3(0, 1.0, -8.0) if self._third_person else Vec3(0, 0, 0.1)
        camera.rotation = Vec3(8 if self._third_person else 0, 0, 0)
        camera.fov      = self.config.fov
        if self._hud_notify:
            self._hud_notify.text    = "  WELCOME TO NOVA CITY  ·  AGENT NOVA ONLINE  "
            self._hud_notify.visible = True
            self._notify_timer = 5.0

    # ── Key input  (match/case — zero elif dispatch) ──────────────────────────

    def _game_input(self, key):
        """Called automatically by Ursina when any key is pressed."""

        if key == 'tab':
            if hasattr(self, '_task_input'):
                self._task_input.visible = not self._task_input.visible
                if self._task_input.visible:
                    self._task_input.active = True
                    self._task_input.text = ""
                else:
                    self._task_input.active = False
            return
            
        if hasattr(self, '_task_input') and self._task_input.active:
            return

        try:
            match key:
                case "v":
                    self._third_person = not self._third_person
                    self._apply_camera_mode()
                case "m":
                    self._show_minimap = not self._show_minimap
                    if self._minimap_bg:
                        self._minimap_bg.enabled = self._show_minimap
                case "t":
                    self._show_tasks = not self._show_tasks
                case "f":
                    self._do_interact()
                case "r":
                    logger.info("Manual task refresh")
                case "escape":
                    mouse.locked  = False
                    mouse.visible = True
                    application.quit()
                case "mouse1":
                    # Re-lock mouse if user clicked to regain focus
                    mouse.locked  = True
                    mouse.visible = False
        except Exception as e:
            logger.error(f"_game_input error: {e}")

    # ── Per-frame master update ───────────────────────────────────────────────

    def _poll_cmd_queue(self) -> None:
        """
        Poll the IPC command queue injected by GameProcessManager.
        Called every frame from _game_update() — non-blocking get_nowait().
        O(1) dict dispatch — zero if/elif.
        """
        _q = getattr(self, "_cmd_queue", None)
        if _q is None:
            return
        from ursina import application
        _handlers = {
            "update_tasks": lambda d: self.update_tasks(d.get("tasks", [])),
            "stop":         lambda d: application.quit(),
        }
        try:
            while True:
                msg = _q.get_nowait()
                handler = _handlers.get(msg.get("cmd", ""))
                handler and handler(msg)
        except Exception:
            pass   # queue.Empty is expected and not an error

    def _game_update(self):
        try:
            logger.debug("frame tick")
            self._poll_cmd_queue()          # IPC from main process — must be first

            from ursina import time as u_time

            dt = min(u_time.dt, 0.05)   # clamp to avoid spiral-of-death
            t  = u_time.time() if callable(u_time.time) else u_time.time
            self._frame_t = t

            with self._lock:
                tasks = list(self._tasks)

            self._update_player(dt)
            self._update_camera_effects(dt, t)
            self._update_sky(t)
            self._update_rain(dt)
            self._update_lightning(dt, t)
            self._update_neon(t)
            self._update_traffic(dt)
            self._update_pedestrians(dt, t)
            self._update_shards(dt, t)
            self._update_monorail(dt, t)
            self._sync_mission_beacons(tasks, t)
            self._check_interactions()
            self._update_hud(tasks, t, dt)
            self._update_minimap(tasks)
        except Exception as e:
            logger.error(f"_game_update error (frame skipped): {e}", exc_info=True)

    # ── Player update ─────────────────────────────────────────────────────────

    def _update_player(self, dt: float):
        if not self._player or not self._cam_pivot:
            return

        # ── Camera rotation via mouse ─────────────────────────────────────
        self._cam_yaw   += mouse.velocity[0] * self.config.look_speed * dt * 10
        self._cam_pitch -= mouse.velocity[1] * self.config.look_speed * dt * 10
        self._cam_pitch  = max(-38, min(25, self._cam_pitch))
        self._cam_pivot.rotation = Vec3(self._cam_pitch, self._cam_yaw, 0)

        # ── WASD movement ─────────────────────────────────────────────────
        yaw_rad = math.radians(self._cam_yaw)
        fwd = Vec3(math.sin(yaw_rad),  0,  math.cos(yaw_rad))
        rgt = Vec3(math.cos(yaw_rad),  0, -math.sin(yaw_rad))

        move_x = (held_keys["d"] - held_keys["a"])
        move_z = (held_keys["w"] - held_keys["s"])
        is_moving = abs(move_x) + abs(move_z) > 0.05

        sprint = held_keys["left shift"] or held_keys["shift"]
        speed  = self.config.sprint_speed if sprint else self.config.move_speed

        if is_moving:
            raw   = fwd * move_z + rgt * move_x
            mag   = raw.length()
            if mag > 0.01:
                direction = raw * (1.0 / mag)
                self._player.x += direction.x * speed * dt
                self._player.z += direction.z * speed * dt
                # Face movement
                target_y = math.degrees(math.atan2(direction.x, direction.z))
                diff = ((target_y - self._player.rotation_y + 180) % 360) - 180
                self._player.rotation_y += diff * min(1.0, dt * 9)
            # Head bob
            self._bob_phase += speed * dt * 7

        # ── Boundary clamp (keep inside city) ─────────────────────────────
        self._player.x = max(-108, min(108, self._player.x))
        self._player.z = max(-108, min(108, self._player.z))

        # ── Jump + gravity ─────────────────────────────────────────────────
        if self._on_ground and held_keys["space"]:
            self._vy = 9.0
            self._on_ground = False
        self._vy -= 24 * dt
        self._player.y += self._vy * dt
        if self._player.y <= 0.85:
            self._player.y = 0.85
            if self._vy < -3:
                self._cam_shake = max(self._cam_shake, abs(self._vy) * 0.04)
            self._vy = 0.0
            self._on_ground = True

        # ── Sprint FOV ────────────────────────────────────────────────────
        target_fov = 98 if (sprint and is_moving) else self.config.fov
        camera.fov += (target_fov - camera.fov) * min(1.0, dt * 6)

    # ── Camera effects ────────────────────────────────────────────────────────

    def _update_camera_effects(self, dt: float, t: float):
        # Branchless shake — multiply-to-zero eliminates if/else
        has_shake = self._cam_shake > 0
        self._cam_shake = max(0.0, self._cam_shake - dt * 3.5 * has_shake)
        camera.rotation_z = random.uniform(-1.0, 1.0) * self._cam_shake * 2

        # Head bob — first-person only; multiply-to-zero suppresses in 3rd-person
        fp_mode = not self._third_person
        is_mov  = (abs(held_keys["w"] - held_keys["s"]) +
                   abs(held_keys["d"] - held_keys["a"])) > 0.05
        do_bob  = fp_mode and is_mov
        bob_y   = math.sin(self._bob_phase) * 0.07  * do_bob
        bob_x   = math.sin(self._bob_phase * 0.5) * 0.035 * do_bob
        do_bob and setattr(camera, "position", Vec3(bob_x, bob_y, 0.1))

    # ── Sky animation ─────────────────────────────────────────────────────────

    def _update_sky(self, t: float):
        if self._moon:
            self._moon.x = 80 + math.sin(t * 0.03) * 5
            self._moon.y = 90 + math.sin(t * 0.02) * 3

    # ── Rain ─────────────────────────────────────────────────────────────────

    def _update_rain(self, dt: float):
        if not self._player:
            return
        px, pz = self._player.x, self._player.z
        for drop in self._rain:
            ent   = drop["ent"]
            ent.y -= drop["speed"] * dt
            if ent.y < 0.05:
                # Reset above player area
                ent.x = px + random.uniform(-50, 50)
                ent.z = pz + random.uniform(-50, 50)
                ent.y = random.uniform(20, 38)
                drop["px"], drop["pz"] = ent.x, ent.z

    # ── Lightning ─────────────────────────────────────────────────────────────

    def _update_lightning(self, dt: float, t: float):
        self._lightning_timer -= dt
        if self._lightning_timer <= 0:
            self._lightning_timer = random.uniform(8, 30)
            if self._lightning_flash:
                invoke(self._do_lightning_flash, delay=0)

    def _do_lightning_flash(self):
        if not self._lightning_flash:
            return
        self._lightning_flash.color = color.rgba(220, 230, 255, 160)
        invoke(self._lightning_fade_out, delay=0.07)

    def _lightning_fade_out(self):
        if self._lightning_flash:
            self._lightning_flash.color = color.rgba(220, 230, 255, 0)

    # ── Neon sign / window flicker ────────────────────────────────────────────

    def _update_neon(self, t: float):
        # Window strips — random flicker
        if self._win_strips:
            n = max(1, len(self._win_strips) // 20)
            for ws in random.sample(self._win_strips, min(n, len(self._win_strips))):
                a = random.randint(60, 220)
                cr = ws.color.r
                cg = ws.color.g
                cb = ws.color.b
                ws.color = color.rgba(cr, cg, cb, a)

        # Neon signs pulse
        for ns in self._neon_signs:
            phase = ns["phase"]
            cr, cg, cb = ns["rgb"]
            ent = ns["ent"]
            match ns["type"]:
                case "sign":
                    a = int(25 + 20 * math.sin(t * 2.2 + phase))
                    ent.color = color.rgba(cr, cg, cb, max(0, a))
                case "blink":
                    a = int(180 + 70 * math.sin(t * 3.5 + phase))
                    ent.color = color.rgba(cr, cg, cb, max(0, a))
                case "terminal":
                    a = int(30 + 20 * math.sin(t * 1.8 + phase))
                    ent.color = color.rgba(cr, cg, cb, max(0, a))

    # ── Traffic ───────────────────────────────────────────────────────────────

    def _update_traffic(self, dt: float):
        for v in self._vehicles:
            body = v["body"]
            wps  = v["waypoints"]
            wi   = v["wp_idx"]
            tgt  = wps[wi % len(wps)]

            dx = tgt.x - body.x
            dz = tgt.z - body.z
            dist = math.hypot(dx, dz)

            # Branchless waypoint advance + movement — zero if/else branches
            at_wp  = dist < 2.0
            v["wp_idx"] = (wi + 1) % len(wps) * at_wp + wi * (not at_wp)
            inv_d  = (not at_wp) / max(dist, 0.001)   # 0 at wp, 1/dist while moving
            speed  = v["speed"]
            body.x += dx * inv_d * speed * dt
            body.z += dz * inv_d * speed * dt
            tgt_rot = math.degrees(math.atan2(dx, dz))
            body.rotation_y = tgt_rot * (not at_wp) + body.rotation_y * at_wp

    # ── Pedestrians ───────────────────────────────────────────────────────────

    def _update_pedestrians(self, dt: float, t: float):
        for npc in self._npcs:
            body  = npc["body"]
            speed = npc["speed"]
            d     = npc["walk_dir"]
            body.x += d.x * speed * dt
            body.z += d.z * speed * dt

            # Branchless direction flip at turnaround — zero if/else branches
            at_turn = abs(body.z - npc["turnaround"]) < 1.0
            flip    = 1 - 2 * at_turn            # 1 = keep direction; -1 = flip
            npc["walk_dir"] = Vec3(d.x, 0, d.z * flip)
            new_ta  = body.z + npc["walk_dir"].z * random.uniform(15, 40)
            npc["turnaround"] = (new_ta * at_turn +
                                 npc["turnaround"] * (not at_turn))

            # Body bob (walking animation)
            npc["bob_phase"] += speed * dt * 7
            body.y = 0.7 + 0.06 * abs(math.sin(npc["bob_phase"]))
            body.rotation_y = math.degrees(math.atan2(d.x, d.z))

            # Boundary clamp
            body.x = max(-108, min(108, body.x))
            body.z = max(-108, min(108, body.z))

    # ── Data shards ───────────────────────────────────────────────────────────

    def _update_shards(self, dt: float, t: float):
        if not self._player:
            return
        px, py, pz = self._player.x, self._player.y, self._player.z
        for s in self._shards:
            ent = s["ent"]
            if not s["alive"]:
                if t >= s["respawn_at"] > 0:
                    s["alive"] = True
                    ent.enabled = True
                    ent.position = s["orig"]
                continue
            # Spin + bob
            ent.rotation_y = t * 90 + id(ent) % 360
            ent.y = 0.5 + 0.22 * math.sin(t * 3.2 + id(ent) % 100)
            # Pulse alpha
            cr, cg, cb = ent._rgb
            ent.color = color.rgba(cr, cg, cb,
                                   int(180 + 50 * math.sin(t * 4 + id(ent))))
            # Collect
            if math.hypot(ent.x - px, ent.z - pz) < 1.8:
                self._collect_shard(s, t)

    def _collect_shard(self, s: Dict, t: float):
        ent = s["ent"]
        self._score += s["xp"]
        self._xp    += s["xp"]
        old_level    = self._level
        self._level  = 1 + self._xp // 200
        s["alive"]     = False
        s["respawn_at"] = t + 90.0
        ent.enabled = False
        self._push_notify(f"  DATA SHARD  +{s['xp']} XP  ")
        if self._level > old_level:
            if self._hud_level_up:
                self._hud_level_up.text    = f"  ★  LEVEL UP!  AGENT LVL {self._level}  ★  "
                self._hud_level_up.visible = True
                self._level_up_timer = 4.5
        # Sparkle burst
        cr, cg, cb = ent._rgb
        for _ in range(8):
            angle  = random.uniform(0, math.tau)
            offset = random.uniform(0.4, 1.2)
            sx = ent.x + math.cos(angle) * offset
            sz = ent.z + math.sin(angle) * offset
            spark = Entity(
                model="sphere",
                position=Vec3(sx, ent.y + 0.2, sz),
                scale=random.uniform(0.07, 0.18),
                color=color.rgba(cr, cg, cb, 220),
            )
            invoke(destroy, spark, delay=random.uniform(0.3, 0.7))

    # ── Monorail ──────────────────────────────────────────────────────────────

    def _update_monorail(self, dt: float, t: float):
        if hasattr(self, "_monorail_train"):
            speed = 22
            self._monorail_train.x += speed * dt
            if self._monorail_train.x > 110:
                self._monorail_train.x = -110

    # ── Mission beacons (task markers, GTA-style) ─────────────────────────────

    def _sync_mission_beacons(self, tasks: List[Dict], t: float):
        active_ids = {tk["task_id"] for tk in tasks}

        # Remove stale beacons
        for tid in list(self._beacons.keys()):
            if tid not in active_ids:
                bd = self._beacons.pop(tid)
                for key in ("pillar", "top_ring", "icon_text", "label", "glow"):
                    if bd.get(key):
                        try:
                            destroy(bd[key])
                        except Exception:
                            pass

        for i, task in enumerate(tasks):
            tid    = task["task_id"]
            status = task.get("status", "pending")
            cr, cg, cb = _rgb(status)

            # Deterministic world position from task hash
            seed = abs(hash(tid)) % 10000
            rng  = random.Random(seed)
            mx   = rng.choice(_BCENTRES) + rng.uniform(-8, 8)
            mz   = rng.choice(_BCENTRES) + rng.uniform(-8, 8)
            my   = 0.0

            # Animate
            pulse_scale = 1.0 + 0.25 * math.sin(t * 2.8 + i)
            ring_y      = 12 + 6 * abs(math.sin(t * 1.5 + i))

            # O(1) dict.get + or-chain — update if exists, create if not
            bd = self._beacons.get(tid)
            bd and bd.get("pillar") and setattr(
                bd["pillar"], "color",
                color.rgba(cr, cg, cb, int(40 + 30 * math.sin(t * 2 + i))))
            bd and bd.get("top_ring") and (
                setattr(bd["top_ring"], "y", ring_y)
                or setattr(bd["top_ring"], "rotation_y", t * 80 + i * 45)
                or setattr(bd["top_ring"], "scale",
                           Vec3(3.5 * pulse_scale, 0.25, 3.5 * pulse_scale)))
            # or-chain: _create_beacon only runs when bd is None (key missing)
            bd or self._create_beacon(
                tid, task, cr, cg, cb, mx, mz, ring_y, status, pulse_scale)

    # ── Beacon factory (called by or-chain in _sync_mission_beacons) ─────────

    def _create_beacon(self, tid: str, task: Dict,
                       cr: int, cg: int, cb: int,
                       mx: float, mz: float, ring_y: float,
                       status: str, pulse_scale: float = 1.0):
        """Spawn a GTA-style mission beacon for *tid* and register it."""
        pillar = Entity(
            model="cube",
            position=Vec3(mx, 10, mz),
            scale=Vec3(0.5, 20, 0.5),
            color=color.rgba(cr, cg, cb, 55),
        )
        glow = Entity(
            model="sphere",
            position=Vec3(mx, 20, mz),
            scale=3.5,
            color=color.rgba(cr, cg, cb, 35),
        )
        top_ring = Entity(
            model="sphere",
            position=Vec3(mx, ring_y, mz),
            scale=Vec3(3.5 * pulse_scale, 0.25, 3.5 * pulse_scale),
            color=color.rgba(cr, cg, cb, 180),
        )
        # Outer halo column (stacked translucent quads)
        for qi in range(4):
            Entity(
                model="quad",
                position=Vec3(mx, 5 + qi * 4, mz),
                scale=Vec3(2.5, 4.0, 1),
                color=color.rgba(cr, cg, cb, 18),
            )
        # Ground ring
        Entity(
            model="sphere",
            position=Vec3(mx, 0.08, mz),
            scale=Vec3(5, 0.06, 5),
            color=color.rgba(cr, cg, cb, 120),
        )
        req_txt = (task.get("summary") or task.get("request") or "TASK")[:28]
        label = Text(
            text=f"[O] {req_txt}\n[{status.upper()}]",
            position=Vec3(mx, 22, mz),
            scale=5.5,
            color=color.rgba(cr, cg, cb, 240),
            billboard=True,
        )
        # Status icon — dict dispatch selects symbol
        _ICONS: Dict[str, str] = {
            "success": "*", "done": "*", "failed": "x",
            "running": ">", "retrying": "~",
        }
        icon_text = Text(
            text=_ICONS.get(status, "!"),
            position=Vec3(mx, 26, mz),
            scale=8,
            color=color.rgba(cr, cg, cb, 255),
            billboard=True,
        )
        self._beacons[tid] = {
            "pillar": pillar, "top_ring": top_ring,
            "glow": glow, "label": label, "icon_text": icon_text,
            "pos": Vec3(mx, 0, mz), "task": task,
        }

    # ── Interaction check ─────────────────────────────────────────────────────

    def _check_interactions(self):
        if not self._player:
            return
        pp = self._player.position
        nearest_dist = 6.0
        nearest = None

        # Check terminals
        for term in self._terminals:
            tp = term["pos"]
            d  = math.hypot(tp.x - pp.x, tp.z - pp.z)
            if d < nearest_dist:
                nearest_dist = d
                nearest = {"type": "terminal", "data": term}

        # Check mission beacons
        for tid, bd in self._beacons.items():
            bp = bd["pos"]
            d  = math.hypot(bp.x - pp.x, bp.z - pp.z)
            if d < nearest_dist:
                nearest_dist = d
                nearest = {"type": "beacon", "data": bd}

        self._interact_target = nearest

        # O(1) dict dispatch — replaces if/elif/else and match/case
        ntype = (nearest or {}).get("type")
        msg   = _INTERACT_PROMPTS.get(ntype, lambda _: "")((nearest or {}).get("data"))
        self._hud_interact and setattr(self._hud_interact, "text", msg or "")

    def _do_interact(self):
        if not self._interact_target:
            return

        def _interact_terminal():
            idx = self._interact_target["data"]["index"]
            with self._lock:
                tasks = list(self._tasks)
            if tasks:
                tk = tasks[idx % len(tasks)]
                req = (tk.get("request") or "")[:60]
                summ = (tk.get("summary") or "")[:60]
                st = tk.get("status", "?").upper()
                steps_done = tk.get("completed_steps", 0)
                steps_tot = tk.get("total_steps", 0)
                if self._hud_mission:
                    self._hud_mission.text = (
                        f"TERMINAL {idx + 1}\n"
                        f"Task: {req}\n"
                        f"Summary: {summ}\n"
                        f"Status: {st}\n"
                        f"Progress: {steps_done}/{steps_tot} steps"
                    )
            else:
                if self._hud_mission:
                    self._hud_mission.text = f"TERMINAL {idx + 1}\n\nNO ACTIVE TASKS\nPress [TAB] to assign a new task."

        def _interact_beacon():
            task = self._interact_target["data"].get("task", {})
            req = (task.get("request") or "")[:60]
            st = task.get("status", "?").upper()
            steps_done = task.get("completed_steps", 0)
            steps_tot = task.get("total_steps", 0)
            errs = " | ".join(str(e) for e in (task.get("error_log") or [])[:2])
            if self._hud_mission:
                self._hud_mission.text = (
                    f"* MISSION OBJECTIVE *\n"
                    f"{req}\n"
                    f"Status: {st}\n"
                    f"Steps: {steps_done}/{steps_tot}\n"
                    f"Errors: {errs or 'None'}"
                )

        INTERACT_MAP: Dict[str, Callable] = {
            "terminal": _interact_terminal,
            "beacon": _interact_beacon
        }
        
        target_type = self._interact_target.get("type", "none")
        INTERACT_MAP.get(target_type, lambda: None)()

    # ── HUD ───────────────────────────────────────────────────────────────────

    def _update_hud(self, tasks: List[Dict], t: float, dt: float):
        running = sum(1 for tk in tasks if tk.get("status") == "running")
        done    = sum(1 for tk in tasks if tk.get("status") in ("success", "done"))
        failed  = sum(1 for tk in tasks if tk.get("status") == "failed")

        # XP / level / cash
        if self._hud_xp:
            self._hud_xp.text = (
                f"XP {self._xp}  ·  LVL {self._level}"
            )
        if self._hud_cash:
            self._hud_cash.text = f"${self._cash:,}"

        # Stars (agent rating) — O(1) table lookup, zero ternary chains
        success_r = (done / max(len(tasks), 1)) if tasks else 1.0
        stars = max(1, round(success_r * 5))
        if self._hud_stars:
            filled   = "*" * stars
            empty    = "-" * (5 - stars)
            star_col = _STAR_COLS[min(stars, 5)]
            self._hud_stars.color = color.rgba(*star_col, 235)
            self._hud_stars.text  = f"{filled}{empty}"

        # Task feed — list * bool trick replaces if/elif dispatch
        # list * True(1) = full list;  list * False(0) = [] → joins to ""
        feed_lines = (
            [f"> NOVA CITY — {len(tasks)} missions"] +
            [f"{_HUD_SYMS.get(tk.get('status','?'), '-')} "
             f"{(tk.get('request') or tk.get('label') or '')[:30]}"
             for tk in tasks[-7:]]
        ) * self._show_tasks
        self._hud_status and setattr(
            self._hud_status, "text", "\n".join(feed_lines))

        # Notification timer
        self._notify_timer -= dt
        if self._notify_timer <= 0 and self._hud_notify:
            self._hud_notify.visible = False

        # Level-up banner timer
        self._level_up_timer -= dt
        if self._level_up_timer <= 0 and self._hud_level_up:
            self._hud_level_up.visible = False

        # Crosshair pulse
        a = int(140 + 60 * math.sin(t * 3))
        if self._crosshair:
            self._crosshair.color = color.rgba(0, 212, 255, a)

    # ── Minimap ───────────────────────────────────────────────────────────────

    def _update_minimap(self, tasks: List[Dict]):
        if not self._show_minimap or not self._player:
            return

        mm_cx, mm_cy = 0.80, -0.37
        mm_half_w, mm_half_h = 0.115, 0.125
        world_range = 120.0
        scale_x = mm_half_w / world_range
        scale_y = mm_half_h / world_range

        pp = self._player.position

        # Player dot stays centred
        if self._mm_player:
            self._mm_player.position = Vec3(mm_cx, mm_cy)

        # Rotate the compass direction indicator based on cam yaw
        # (not implemented — just keep player centred, world offsets scroll)

        # Mission beacon dots
        active_ids = {tk["task_id"] for tk in tasks}
        for tid in list(self._minimap_dots.keys()):
            if tid not in active_ids:
                try:
                    destroy(self._minimap_dots.pop(tid))
                except Exception:
                    pass

        for tk in tasks:
            tid    = tk["task_id"]
            status = tk.get("status", "pending")
            cr, cg, cb = _rgb(status)

            if tid not in self._beacons:
                continue
            bp = self._beacons[tid]["pos"]
            dx = (bp.x - pp.x) * scale_x
            dz = (bp.z - pp.z) * scale_y
            dot_x = mm_cx + dx
            dot_y = mm_cy - dz

            # Clamp to minimap bounds
            dot_x = max(mm_cx - mm_half_w + 0.005,
                        min(mm_cx + mm_half_w - 0.005, dot_x))
            dot_y = max(mm_cy - mm_half_h + 0.005,
                        min(mm_cy + mm_half_h - 0.005, dot_y))

            try:
                # Or-chain: get existing dot; only create+cache when absent
                # dict.__setitem__ returns None → 'or' then fetches from dict
                dot = (
                    self._minimap_dots.get(tid)
                    or self._minimap_dots.__setitem__(
                        tid,
                        Entity(model="quad", position=Vec3(dot_x, dot_y),
                               scale=Vec3(0.010, 0.012, 1),
                               color=color.rgba(cr, cg, cb, 220),
                               parent=camera.ui))
                    or self._minimap_dots[tid]
                )
                dot.x     = dot_x
                dot.y     = dot_y
                dot.color = color.rgba(cr, cg, cb, 220)
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    #  Public properties
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def score(self) -> int:
        return self._score
