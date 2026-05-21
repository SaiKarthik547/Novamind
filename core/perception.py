"""
core/perception.py

The Central Nervous System for OS interaction.
Implements the Perceive -> Act -> Verify loop. 
Provides a unified ScreenState by wrapping UIA and OCR fallbacks.
Agents must consult this engine before taking actions.
"""

import logging
import time
from typing import List, Optional, Tuple, Dict
from dataclasses import dataclass

try:
    import pyautogui
except ImportError:
    pyautogui = None

try:
    from PIL import ImageGrab
except ImportError:
    ImageGrab = None

try:
    import easyocr
except ImportError:
    easyocr = None

from core.uia_executor import (
    UIAExecutor, UIElement, UIWindow,
    UIAError, UIAUnavailableError, ElementNotFoundError, WindowNotFoundError
)

logger = logging.getLogger("PerceptionEngine")

@dataclass
class UIElementState:
    """A verified, actionable UI element state."""
    name: str
    automation_id: str
    center: Tuple[int, int]
    bounding_rect: Optional[Tuple[int, int, int, int]]  # (left, top, right, bottom)
    source: str  # 'uia' or 'ocr'
    confidence: float

@dataclass
class ScreenState:
    """The complete perceived state of the screen/window."""
    window_title: str
    elements: List[UIElementState]
    timestamp: float

class PerceptionEngine:
    def __init__(self):
        self.uia = UIAExecutor()
        self._ocr_reader = None
        self._last_state: Optional[ScreenState] = None

    def _get_ocr_reader(self):
        if self._ocr_reader is None and easyocr is not None:
            logger.info("Initializing EasyOCR reader for perception fallback...")
            self._ocr_reader = easyocr.Reader(['en'], gpu=False)
        return self._ocr_reader

    def get_window(self, title_contains: str, timeout: float = 5.0) -> Optional[UIWindow]:
        """Attempt to find a window using UIA, raising errors if absent."""
        try:
            return self.uia.find_window(title_contains, timeout=timeout)
        except WindowNotFoundError as e:
            logger.warning(f"Perception UIA Window Fail: {e}")
            return None
        except UIAUnavailableError as e:
            logger.warning(f"Perception UIA Unavailable: {e}")
            return None

    def find_element(self, window_title: str, element_name: str) -> Optional[UIElementState]:
        """
        Unified search: 
        1. Tries UIA.
        2. If UIA fails, takes a screenshot and tries OCR to find the text.
        """
        # Step 1: Try UIA
        if self.uia.available:
            try:
                win = self.uia.find_window(window_title, timeout=2.0)
                el = self.uia.find_element(win, name=element_name)
                center = el.center
                if center:
                    rect = el.bounding_rect
                    bbox = (rect.left, rect.top, rect.right, rect.bottom) if rect else None
                    return UIElementState(
                        name=el.name,
                        automation_id=el.automation_id,
                        center=center,
                        bounding_rect=bbox,
                        source='uia',
                        confidence=1.0
                    )
            except UIAError as e:
                logger.debug(f"Perception Engine: UIA search failed ({e}). Falling back to OCR.")

        # Step 2: Fallback to OCR
        logger.info(f"Triggering OCR fallback to find '{element_name}'")
        reader = self._get_ocr_reader()
        if not reader or not ImageGrab:
            logger.error("OCR fallback failed: easyocr or PIL not installed.")
            return None

        screenshot = ImageGrab.grab()
        # EasyOCR expects numpy array or file path
        try:
            import numpy as np
            img_np = np.array(screenshot)
            results = reader.readtext(img_np)
            
            # Find the best text match
            best_match = None
            best_conf = 0.0
            for (bbox, text, prob) in results:
                if element_name.lower() in text.lower() and prob > best_conf:
                    best_match = bbox
                    best_conf = prob
                    
            if best_match and best_conf > 0.5:
                # bbox is [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
                x1, y1 = int(best_match[0][0]), int(best_match[0][1])
                x2, y2 = int(best_match[2][0]), int(best_match[2][1])
                center_x = x1 + (x2 - x1) // 2
                center_y = y1 + (y2 - y1) // 2
                
                return UIElementState(
                    name=element_name,
                    automation_id="",
                    center=(center_x, center_y),
                    bounding_rect=(x1, y1, x2, y2),
                    source='ocr',
                    confidence=float(best_conf)
                )
        except Exception as e:
            logger.error(f"OCR processing failed: {e}")
            
        return None

    def execute_click(self, element_state: UIElementState) -> bool:
        """Execute a click on a verified state."""
        if not element_state or not element_state.center:
            logger.error("PerceptionEngine: Cannot click invalid state.")
            return False
            
        try:
            if pyautogui:
                pyautogui.click(*element_state.center)
                return True
            else:
                logger.error("pyautogui not available for click.")
                return False
        except Exception as e:
            logger.error(f"Click execution failed: {e}")
            return False
