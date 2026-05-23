from enum import Enum
from dataclasses import dataclass

class ExecutionMode(Enum):
    FOREGROUND = "FOREGROUND"           # Visible on active user desktop
    BACKGROUND = "BACKGROUND"           # Running invisibly but sharing session
    HEADLESS = "HEADLESS"               # Completely invisible, no display required
    ISOLATED = "ISOLATED"               # Running in a dedicated abstract session
    LEGACY_FOREGROUND = "LEGACY_FOREGROUND" # Non-deterministic PyAutoGUI

@dataclass
class ExecutionContext:
    """
    Defines the boundaries and visibility of an execution session.
    """
    mode: ExecutionMode
    session_id: str
    requires_gpu: bool = False
    requires_compositor: bool = False
