"""
vision/screen_analyzer.py

ScreenAnalyzer: given a screenshot, understands what is on screen.
Used by Brain to make decisions when UIA fails (non-Windows or UIA crash).

Components:
  - Window boundary detection  (contour-based via OpenCV)
  - Full-screen OCR            (Tesseract → EasyOCR → empty string)
  - UI element detection       (contour + aspect-ratio heuristics)
  - ScreenState dataclass      (typed result passed to Brain)

Zero if-elif routing — all dispatch via O(1) dict lookup.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("ScreenAnalyzer")

try:
    from PIL import Image, ImageGrab
    PIL_OK = True
except ImportError:
    PIL_OK = False

try:
    import numpy as np
    NUMPY_OK = True
except ImportError:
    NUMPY_OK = False

try:
    import cv2
    CV2_OK = True
except ImportError:
    CV2_OK = False


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class DetectedWindow:
    title: str
    bounds: Tuple[int, int, int, int]   # (left, top, right, bottom)
    confidence: float = 1.0


@dataclass
class TextRegion:
    text: str
    bounds: Tuple[int, int, int, int]
    confidence: float = 1.0


@dataclass
class UIElementRegion:
    kind: str                           # "button" | "input" | "checkbox" | "unknown"
    bounds: Tuple[int, int, int, int]
    center: Tuple[int, int] = field(default=(0, 0))


@dataclass
class ScreenState:
    windows:     List[DetectedWindow]  = field(default_factory=list)
    text_regions: List[TextRegion]     = field(default_factory=list)
    ui_elements:  List[UIElementRegion] = field(default_factory=list)
    raw_text:     str                  = ""
    screenshot:   Optional[object]     = None   # PIL.Image


# ── OCR helpers ───────────────────────────────────────────────────────────────

def _ocr_tesseract(image: "Image.Image") -> Tuple[str, List[TextRegion]]:
    try:
        import pytesseract
        data = pytesseract.image_to_data(
            image, output_type=pytesseract.Output.DICT
        )
        regions = [
            TextRegion(
                text=data["text"][i],
                bounds=(
                    data["left"][i], data["top"][i],
                    data["left"][i] + data["width"][i],
                    data["top"][i]  + data["height"][i],
                ),
                confidence=int(data["conf"][i]) / 100.0,
            )
            for i in range(len(data["text"]))
            if data["text"][i].strip() and int(data["conf"][i]) >= 20
        ]
        raw = " ".join(r.text for r in regions)
        return raw, regions
    except Exception as e:
        logger.debug(f"Tesseract OCR: {e}")
        return "", []


def _ocr_easyocr(image: "Image.Image") -> Tuple[str, List[TextRegion]]:
    try:
        import easyocr, io
        reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        results = reader.readtext(buf.getvalue())
        regions = []
        for bbox, text, conf in results:
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            regions.append(TextRegion(
                text=text,
                bounds=(int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))),
                confidence=float(conf),
            ))
        raw = " ".join(r.text for r in regions)
        return raw, regions
    except Exception as e:
        logger.debug(f"EasyOCR: {e}")
        return "", []


# O(1) dispatch: try Tesseract first, then EasyOCR
_OCR_CHAIN = [_ocr_tesseract, _ocr_easyocr]


def _run_ocr(image: "Image.Image") -> Tuple[str, List[TextRegion]]:
    """Run OCR, trying each engine in order, return first non-empty result."""
    for fn in _OCR_CHAIN:
        raw, regions = fn(image)
        _has_result = {True: lambda: (raw, regions)}
        action = _has_result.get(bool(raw))
        if action:
            return action()
    return "", []


# ── Window detection ──────────────────────────────────────────────────────────

def _detect_windows_cv2(image: "Image.Image") -> List[DetectedWindow]:
    """
    Heuristic: find large rectangular contours with title-bar-like aspect.
    Works even without UIA — pure vision.
    """
    _unavail = {True: lambda: []}
    unavail = _unavail.get(not (CV2_OK and NUMPY_OK))
    if unavail:
        return unavail()
    try:
        img_np  = np.array(image.convert("RGB"))
        gray    = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
        edges   = cv2.Canny(gray, 50, 150)
        contours, _ = cv2.findContours(
            edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        h, w = gray.shape
        min_area = (w * h) * 0.04   # at least 4% of screen

        windows = []
        for cnt in contours:
            x, y, cw, ch = cv2.boundingRect(cnt)
            area = cw * ch
            is_large = area >= min_area
            _add = {True: lambda: windows.append(DetectedWindow(
                title="",
                bounds=(x, y, x + cw, y + ch),
                confidence=0.5,
            ))}
            _add.get(is_large, lambda: None)()
        return windows
    except Exception as e:
        logger.debug(f"_detect_windows_cv2: {e}")
        return []


# ── UI element detection ──────────────────────────────────────────────────────

_ASPECT_KIND: Dict[Tuple[bool, bool], str] = {
    (True,  False): "button",
    (False, True):  "input",
    (False, False): "unknown",
    (True,  True):  "checkbox",
}


def _classify_element(w: int, h: int) -> str:
    """Classify a rectangular region by aspect ratio."""
    is_wide   = (w / max(h, 1)) > 1.5
    is_square = 0.7 < (w / max(h, 1)) < 1.4
    return _ASPECT_KIND.get((is_wide, is_square), "unknown")


def _detect_ui_elements_cv2(image: "Image.Image") -> List[UIElementRegion]:
    _unavail = {True: lambda: []}
    unavail = _unavail.get(not (CV2_OK and NUMPY_OK))
    if unavail:
        return unavail()
    try:
        img_np = np.array(image.convert("RGB"))
        gray   = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
        contours, _ = cv2.findContours(
            thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        elements = []
        for cnt in contours:
            x, y, cw, ch = cv2.boundingRect(cnt)
            _too_small = {True: lambda: None}
            skip = _too_small.get(cw < 10 or ch < 5 or cw > 800 or ch > 200)
            if skip:
                continue
            kind = _classify_element(cw, ch)
            elements.append(UIElementRegion(
                kind=kind,
                bounds=(x, y, x + cw, y + ch),
                center=(x + cw // 2, y + ch // 2),
            ))
        return elements
    except Exception as e:
        logger.debug(f"_detect_ui_elements_cv2: {e}")
        return []


# ── ScreenAnalyzer ────────────────────────────────────────────────────────────

class ScreenAnalyzer:
    """
    Given a screenshot, understand what is on screen.
    Used by Brain to make decisions when UIA fails.
    All methods return typed data — never raw dicts.
    """

    def analyze(self, screenshot: Optional["Image.Image"] = None) -> ScreenState:
        """
        Full analysis pipeline: grab screenshot if not provided, then run
        window detection, OCR, and UI element detection in sequence.
        """
        _no_pil = {True: lambda: ScreenState()}
        no_pil = _no_pil.get(not PIL_OK)
        if no_pil:
            logger.warning("ScreenAnalyzer: PIL not available")
            return no_pil()

        img = screenshot or self._grab()
        _no_img = {True: lambda: ScreenState()}
        no_img = _no_img.get(img is None)
        if no_img:
            return no_img()

        raw_text, text_regions = _run_ocr(img)
        windows    = _detect_windows_cv2(img)
        ui_elements = _detect_ui_elements_cv2(img)

        return ScreenState(
            windows=windows,
            text_regions=text_regions,
            ui_elements=ui_elements,
            raw_text=raw_text,
            screenshot=img,
        )

    def grab_and_analyze(self) -> ScreenState:
        """Convenience: grab screenshot then analyze."""
        return self.analyze(self._grab())

    def find_text_on_screen(self, text: str,
                             min_confidence: float = 0.2) -> List[TextRegion]:
        """Return all TextRegions whose text contains *text* (case-insensitive)."""
        state = self.analyze()
        text_lower = text.lower()
        return [
            r for r in state.text_regions
            if text_lower in r.text.lower() and r.confidence >= min_confidence
        ]

    @staticmethod
    def _grab() -> Optional["Image.Image"]:
        _no_pil = {True: lambda: None}
        no_pil = _no_pil.get(not PIL_OK)
        if no_pil:
            return no_pil()
        try:
            return ImageGrab.grab()
        except Exception as e:
            logger.warning(f"ScreenAnalyzer._grab: {e}")
            return None
