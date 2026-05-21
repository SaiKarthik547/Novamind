"""
core/element_finder.py

Unified three-strategy element finder used by ALL agents.
Strategy order: UIA → OCR → Template → (coordinate passthrough).

Refactored to enforce strict actionability and explicit state propagation.
No dict-dispatch logic. Raises ElementNotFoundError when an element cannot be located.
"""

import logging
import time
import threading
import os
from dataclasses import dataclass
from typing import Any, Optional, Tuple, Callable, Dict, List

logger = logging.getLogger("ElementFinder")

class ElementNotFoundError(Exception):
    pass

class DependencyMissingError(Exception):
    pass


try:
    from core.uia_executor import UIAExecutor, UIElement, UIAError
    _UIA_EXEC = UIAExecutor()
    UIA_OK = _UIA_EXEC.available
except Exception as _e:
    logger.warning(f"ElementFinder: UIA not available ({_e})")
    _UIA_EXEC = None
    UIA_OK = False

try:
    import pyautogui
    PYAUTOGUI_OK = True
except ImportError:
    PYAUTOGUI_OK = False

try:
    from PIL import Image
    PIL_OK = True
except ImportError:
    PIL_OK = False


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class FoundElement:
    """
    Result of a successful element search.
    Always has screen-coordinate centre for clicking.
    `uia_element` is populated only when found via UIA.
    `strategy` records which strategy succeeded.
    """
    x: int
    y: int
    strategy: str
    confidence: float = 1.0
    bounding_box: Optional[Tuple[int, int, int, int]] = None
    uia_element: Optional[object] = None

    def click(self) -> None:
        """Click the element via pyautogui."""
        if not PYAUTOGUI_OK:
            raise DependencyMissingError("Cannot click: pyautogui is not installed.")
        pyautogui.click(self.x, self.y)

    def __repr__(self) -> str:
        return (
            f"<FoundElement strategy={self.strategy!r} "
            f"center=({self.x},{self.y}) conf={self.confidence:.2f}>"
        )


# ── Strategy 1: Windows UI Automation ─────────────────────────────────────────

class _UIAStrategy:
    """Semantic element finding via UIA — most reliable on Windows."""

    def find(self, description: str,
             window_title: Optional[str] = None,
             context: Optional[Dict] = None) -> FoundElement:
        
        if not UIA_OK or not _UIA_EXEC:
            raise DependencyMissingError("UIA is not available.")

        try:
            window = None
            if window_title:
                window = _UIA_EXEC.find_window(window_title, timeout=2.0)

            try:
                el = _UIA_EXEC.find_element(window, name=description)
            except UIAError:
                el = _UIA_EXEC.find_element(window, automation_id=description)

            centre = el.center
            if not centre:
                raise ElementNotFoundError("UIA found element, but it has no valid screen coordinates.")

            bb = el.bounding_rect
            bb_tuple = (bb.left, bb.top, bb.right, bb.bottom) if bb else None
            
            return FoundElement(
                x=centre[0], y=centre[1], strategy="uia",
                confidence=1.0, bounding_box=bb_tuple, uia_element=el,
            )
            
        except UIAError as e:
            raise ElementNotFoundError(f"UIA search failed: {e}")
        except Exception as e:
            raise ElementNotFoundError(f"Unexpected UIA error: {e}")


# ── Strategy 2: OCR ───────────────────────────────────────────────────────────

class _OCRStrategy:
    """Find text on screen via Tesseract/EasyOCR; return bounding-box centre."""

    def find(self, description: str,
             window_title: Optional[str] = None,
             context: Optional[Dict] = None) -> FoundElement:
        
        if not PYAUTOGUI_OK:
            raise DependencyMissingError("OCR requires pyautogui for screenshots.")

        try:
            screenshot = context.get("screenshot") if context else None
            if screenshot is None:
                screenshot = pyautogui.screenshot()
            
            result = self._tesseract_find(screenshot, description)
            if result:
                return result
                
            result = self._easyocr_find(screenshot, description)
            if result:
                return result
                
            raise ElementNotFoundError(f"Text '{description}' not found via OCR on screen.")
            
        except Exception as e:
            if isinstance(e, ElementNotFoundError):
                raise
            raise ElementNotFoundError(f"OCR execution failed: {e}")

    def _tesseract_find(self, image, text: str) -> Optional[FoundElement]:
        try:
            import pytesseract
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
            text_lower = text.lower()
            
            for i, word in enumerate(data.get("text", [])):
                if text_lower in word.lower() and int(data["conf"][i]) >= 20:
                    x = data["left"][i] + data["width"][i] // 2
                    y = data["top"][i] + data["height"][i] // 2
                    return FoundElement(
                        x=x, y=y, strategy="ocr",
                        confidence=int(data["conf"][i]) / 100.0,
                        bounding_box=(
                            data["left"][i], data["top"][i],
                            data["left"][i] + data["width"][i],
                            data["top"][i] + data["height"][i],
                        ),
                    )
            return None
        except Exception:
            return None

    def _easyocr_find(self, image, text: str) -> Optional[FoundElement]:
        try:
            import easyocr, io
            global _EASYOCR_READER
            if _EASYOCR_READER is None:
                logger.info("Initializing EasyOCR reader...")
                _EASYOCR_READER = easyocr.Reader(["en"], gpu=False, verbose=False)
            
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            results = _EASYOCR_READER.readtext(buf.getvalue())
            text_lower = text.lower()
            
            for bbox, word, conf in results:
                if text_lower in word.lower() and conf > 0.2:
                    xs = [pt[0] for pt in bbox]
                    ys = [pt[1] for pt in bbox]
                    return FoundElement(
                        x=int(sum(xs) / len(xs)), y=int(sum(ys) / len(ys)),
                        strategy="ocr", confidence=float(conf),
                        bounding_box=(int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))),
                    )
            return None
        except Exception:
            return None


# ── Strategy 3: Template matching ────────────────────────────────────────────

_TEMPLATE_DIRS = ("assets/templates", "resources/templates", "data/templates")


class _TemplateStrategy:
    """OpenCV template-image matching against known button/icon images."""

    def find(self, description: str,
             window_title: Optional[str] = None,
             context: Optional[Dict] = None) -> FoundElement:
        
        candidates = [os.path.join(d, f"{description}.png") for d in _TEMPLATE_DIRS]
        existing = [p for p in candidates if os.path.isfile(p)]
        
        if not existing:
            raise ElementNotFoundError(f"No template file found for '{description}'.")
            
        result = self._match(existing[0], context=context)
        if result:
            return result
            
        raise ElementNotFoundError(f"Template '{description}' not detected on screen.")

    def _match(self, template_path: str, context: Optional[Dict] = None) -> Optional[FoundElement]:
        try:
            import cv2, numpy as np
            screenshot = context.get("screenshot") if context else None
            if screenshot is None:
                if not PYAUTOGUI_OK:
                    return None
                screenshot = pyautogui.screenshot()
                
            screen_bgr = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
            tmpl = cv2.imread(template_path)
            
            if tmpl is None:
                return None
                
            result = cv2.matchTemplate(screen_bgr, tmpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            
            if max_val >= 0.75:
                th, tw = tmpl.shape[:2]
                return FoundElement(
                    x=max_loc[0] + tw // 2, y=max_loc[1] + th // 2,
                    strategy="template", confidence=float(max_val),
                    bounding_box=(max_loc[0], max_loc[1], max_loc[0] + tw, max_loc[1] + th),
                )
            return None
        except Exception:
            return None


# ── ElementFinder ─────────────────────────────────────────────────────────────

class ElementFinder:
    """Unified finder. strategy='auto' tries all in order; specific key runs one."""

    def __init__(self) -> None:
        self._strategies: Dict[str, Callable] = {
            "uia":      _UIAStrategy().find,
            "ocr":      _OCRStrategy().find,
            "template": _TemplateStrategy().find,
        }

    def _auto(self, description: str, window_title: Optional[str]) -> FoundElement:
        screenshot = pyautogui.screenshot() if PYAUTOGUI_OK else None
        ctx = {"screenshot": screenshot}
        
        errors = []
        
        for strat_name in ["uia", "ocr", "template"]:
            try:
                strat_func = self._strategies[strat_name]
                if strat_name == "uia":
                    return strat_func(description, window_title)
                else:
                    return strat_func(description, window_title, context=ctx)
            except (ElementNotFoundError, DependencyMissingError) as e:
                errors.append(str(e))
                continue
                
        raise ElementNotFoundError(f"Element '{description}' not found using any strategy. Errors: {errors}")

    def find(
        self,
        description: str,
        window_title: Optional[str] = None,
        strategy: str = "auto",
        retry: int = 1,
        retry_delay: float = 0.5,
    ) -> Optional[FoundElement]:
        """Find a UI element by semantic description."""
        
        for attempt in range(max(1, retry)):
            if attempt > 0:
                time.sleep(retry_delay)
                
            try:
                if strategy == "auto":
                    result = self._auto(description, window_title)
                else:
                    runner = self._strategies.get(strategy)
                    if not runner:
                        raise ValueError(f"Unknown strategy: {strategy}")
                    result = runner(description, window_title)
                    
                logger.info(
                    f"ElementFinder: '{description}' found via "
                    f"{result.strategy} at ({result.x},{result.y})"
                )
                return result
            except (ElementNotFoundError, DependencyMissingError) as e:
                logger.debug(f"Attempt {attempt + 1} failed: {e}")
                
        logger.warning(
            f"ElementFinder: '{description}' not found "
            f"(strategy={strategy!r}, attempts={retry})"
        )
        return None

    def click(
        self,
        description: str,
        window_title: Optional[str] = None,
        strategy: str = "auto",
        retry: int = 2,
    ) -> bool:
        """Find and click. Returns True on success."""
        el = self.find(description, window_title, strategy, retry)
        if el:
            try:
                el.click()
                return True
            except DependencyMissingError as e:
                logger.error(f"Click failed: {e}")
                return False
        return False


# ── Module-level singleton ────────────────────────────────────────────────────

_finder: Optional[ElementFinder] = None
_EASYOCR_READER: Any = None
_FINDER_LOCK = threading.Lock()

def get_finder() -> ElementFinder:
    global _finder
    if _finder is None:
        with _FINDER_LOCK:
            if _finder is None:
                _finder = ElementFinder()
    return _finder
