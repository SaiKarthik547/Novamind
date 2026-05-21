"""
config.py

Single source of truth for every magic number in NovaMind.
Import from here — never hardcode values in agents or core modules.

Zero if-elif — all values are constants or O(1) dict lookups.
"""

from typing import Dict, Tuple, FrozenSet

# ── Timing (seconds) ──────────────────────────────────────────────────────────

PYAUTOGUI_PAUSE          = 0.05   # pyautogui.PAUSE — always set on import
DRAG_DURATION            = 0.35   # default drag movement duration
FOCUS_MAX_WAIT           = 2.0    # assert_window_focused max poll time
PAINT_OPEN_WAIT          = 1.5    # sleep after spawning mspaint
PAINT_WINDOW_POLL        = 0.3    # interval while waiting for Paint window
PAINT_WINDOW_POLL_MAX    = 20     # max poll iterations for Paint window
PAINT_MAXIMIZE_WAIT      = 0.5    # sleep after Win+Up maximize
PAINT_FOCUS_WAIT         = 0.3    # sleep after window.activate()
COLOR_DIALOG_WAIT        = 0.6    # sleep after clicking "Edit colors"
COLOR_OK_WAIT            = 0.3    # sleep after clicking OK in color dialog
CANVAS_SCAN_START        = 80     # pixel row where white-row scan begins
CANVAS_SCAN_END          = 280    # pixel row where scan gives up
CANVAS_FALLBACK_TOP      = 125    # fallback canvas top when scan finds nothing
CANVAS_BORDER_PAD        = 4      # pixel inset from window edge for canvas rect
CANVAS_BOTTOM_PAD        = 30     # pixel inset from window bottom for canvas rect
CANVAS_WHITE_THRESHOLD   = 0.70   # fraction of white pixels to call a row "canvas"
CANVAS_WHITE_VALUE       = 240    # per-channel minimum to count as "white"
DIFF_PIXEL_THRESHOLD     = 15     # per-channel delta to count a pixel as "changed"
DIFF_FRACTION_THRESHOLD  = 0.005  # fraction of changed pixels to call images "different"
STABLE_CHECK_INTERVAL    = 0.15   # sleep between stability-check screenshots
STABLE_FOR               = 1.0    # seconds of stability required
STATUS_LOOP_INTERVAL     = 2.0    # main status refresh loop interval
BRAIN_RETRY_SLEEP        = 0.5    # sleep between brain execution retries
GAME_READY_TIMEOUT       = 15.0   # seconds to wait for game process ready signal
GAME_STOP_JOIN_TIMEOUT   = 5.0    # seconds to join game process on stop
SCHEDULER_POLL           = 1.0    # task scheduler poll interval
ASYNC_TASK_TIMEOUT       = 120    # future.result() timeout for brain async tasks
RECOVERY_CONFIDENCE_MIN  = 0.7    # VerifierAgent minimum confidence to mark success

# ── Retry counts ──────────────────────────────────────────────────────────────

MAX_RETRIES              = 3
ELEMENT_FINDER_RETRIES   = 2
WINDOW_POLL_RETRIES      = 20

# ── DPI ───────────────────────────────────────────────────────────────────────

DPI_SCALE_MIN            = 0.5    # guard against absurdly low reported DPI
DPI_SCALE_DEFAULT        = 1.0

# ── pyautogui safety ─────────────────────────────────────────────────────────

FAILSAFE                 = True
PYAUTOGUI_TYPEWRITE_IV   = 0.03   # typewrite interval for short ASCII strings
PYAUTOGUI_PASTE_WAIT     = 0.08   # sleep before Ctrl+V paste
PYAUTOGUI_PASTE_AFTER    = 0.12   # sleep after Ctrl+V paste
HUMAN_TYPE_LO            = 0.04   # _human_type min delay per char
HUMAN_TYPE_HI            = 0.12   # _human_type max delay per char
SMART_TYPE_MAX_ASCII_LEN = 40     # max length to typewrite directly

# ── Drawing ───────────────────────────────────────────────────────────────────

DRAWING_STROKE_MIN_PTS   = 2      # strokes with fewer points are discarded
DRAWING_STROKE_MAX_GAP   = 15     # max pixel distance between consecutive points
DRAWING_MIN_STROKES      = 30
DRAWING_MAX_STROKES      = 200
DRAWING_COORD_MARGIN     = 5      # minimum pixel margin from canvas edge

# ── LLM / brain ──────────────────────────────────────────────────────────────

LLM_TASK_TYPE_CODING     = "coding"
LLM_QUICK_REQUEST_TIMEOUT= 30

# ── UIA Automation IDs (MS Paint Edit Colors dialog) ─────────────────────────

PAINT_UIA_RED_FIELD      = "703"
PAINT_UIA_GREEN_FIELD    = "704"
PAINT_UIA_BLUE_FIELD     = "705"

# ── Window title substrings ───────────────────────────────────────────────────

TITLE_PAINT              = "Paint"
TITLE_EDIT_COLORS        = "Edit Colors"

# ── OCR confidence thresholds ─────────────────────────────────────────────────

OCR_TESSERACT_MIN_CONF   = 20     # Tesseract word confidence (0-100)
OCR_EASYOCR_MIN_CONF     = 0.2    # EasyOCR per-word confidence (0.0-1.0)

# ── Template matching ─────────────────────────────────────────────────────────

TEMPLATE_MATCH_THRESHOLD = 0.75   # cv2.TM_CCOEFF_NORMED minimum

# ── Colors ────────────────────────────────────────────────────────────────────

COLOR_BLACK   : Tuple[int,int,int] = (0,   0,   0)
COLOR_GRAY    : Tuple[int,int,int] = (80,  80,  80)
COLOR_SILVER  : Tuple[int,int,int] = (192, 192, 192)
COLOR_YELLOW  : Tuple[int,int,int] = (255, 200, 0)
COLOR_RED     : Tuple[int,int,int] = (220, 30,  30)
COLOR_LIGHTBLUE: Tuple[int,int,int]= (173, 216, 230)

# ── Fallback action map for task_parser ──────────────────────────────────────

FALLBACK_ACTION_MAP: Dict[str, Dict] = {
    "application_agent": {
        "action":     "open_and_draw",
        "parameters": {"description": None},
    },
    "file_agent": {
        "action":     "read_file",
        "parameters": {"path": None},
    },
    "system_agent": {
        "action":     "run_command",
        "parameters": {"command_line": None},
    },
    "browser_agent": {
        "action":     "navigate",
        "parameters": {"url": None},
    },
    "code_agent": {
        "action":     "execute_code",
        "parameters": {"code": None},
    },
}

FALLBACK_DEFAULT_ACTION: Dict = {
    "action":     "run_command",
    "parameters": {"command_line": None},
}

# ── Risk levels ───────────────────────────────────────────────────────────────

RISK_SAFE   = 0
RISK_LOW    = 1
RISK_MEDIUM = 2
RISK_HIGH   = 3

# ── Valid state transitions (mirrors brain.py VALID_TRANSITIONS) ──────────────

VALID_TRANSITIONS: FrozenSet[Tuple[str, str]] = frozenset({
    ("idle",      "planning"),
    ("planning",  "executing"),
    ("executing", "verifying"),
    ("verifying", "success"),
    ("verifying", "retrying"),
    ("retrying",  "executing"),
    ("executing", "failed"),
    ("retrying",  "failed"),
    ("failed",    "idle"),
    ("success",   "idle"),
})

# ── Game performance settings ─────────────────────────────────────────────────────
# Set GAME_LOW_PERF_MODE = True on older/slower machines to reduce GPU usage.

GAME_RESOLUTION:    Tuple[int, int] = (1280, 720)   # reduced from 1440×900
GAME_RAIN_COUNT:    int             = 100            # reduced from 280
GAME_NPC_COUNT:     int             = 8              # reduced from 22
GAME_VEHICLE_COUNT: int             = 4              # reduced from 14
GAME_LOW_PERF_MODE: bool            = False          # flip to True on low-end machines
