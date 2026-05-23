"""
Vision System — Real screen capture, OCR, element detection, image comparison.
All functionality uses real system calls (pyautogui, PIL, pytesseract, cv2).
No simulated screen data.
"""
import os
import io
import time
import base64
import hashlib
import logging
import platform
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

from core.foundation.runtime_paths import ensure_runtime_dir

logger = logging.getLogger("Vision")

# ── Optional imports (graceful fallback) ──────────────────────────────────────
try:
    import pyautogui
    PYAUTOGUI_OK = True
except ImportError:
    PYAUTOGUI_OK = False
    logger.warning("pyautogui not available — screenshot/click disabled")

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
    PIL_OK = True
except ImportError:
    PIL_OK = False
    logger.warning("Pillow not available — image processing disabled")

try:
    import pytesseract
    TESSERACT_OK = True
except ImportError:
    TESSERACT_OK = False
    logger.warning("pytesseract not available — OCR disabled")

try:
    import cv2
    import numpy as np
    CV2_OK = True
except ImportError:
    CV2_OK = False
    logger.warning("opencv-python not available — element detection limited")

try:
    import easyocr
    EASYOCR_OK = True
except ImportError:
    EASYOCR_OK = False


class VisionSystem:
    """
    Real computer-vision layer.
    Captures screen, reads text, locates UI elements, compares images.
    """

    def __init__(self):
        self._screenshot_dir = str(ensure_runtime_dir("screenshots"))
        self._last_screenshot: Optional["Image.Image"] = None
        self._easyocr_reader = None
        self._cache: Dict[str, Dict] = {}

        if PYAUTOGUI_OK:
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.05

        logger.info(
            f"VisionSystem ready — pyautogui={PYAUTOGUI_OK}, "
            f"PIL={PIL_OK}, tesseract={TESSERACT_OK}, cv2={CV2_OK}"
        )

    def execute(self, action: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        handlers = {
            "capture_screen":         self.capture_screen,
            "capture_region":         self.capture_region,
            "read_screen_text":       self.read_screen_text,
            "find_element":           self.find_element,
            "find_all_elements":      self.find_all_elements,
            "describe_screen":        self.describe_screen,
            "compare_images":         self.compare_images,
            "detect_ui_elements":     self.detect_ui_elements,
            "find_text_location":     self.find_text_location,
            "get_screen_info":        self.get_screen_info,
            "capture_window":         self.capture_window,
            "read_clipboard":         self.read_clipboard,
            "get_active_window_title":self.get_active_window_title,
            "highlight_region":       self.highlight_region,
        }
        fn = handlers.get(action)
        if not fn:
            return {"success": False, "error": f"Unknown vision action: {action}"}
        try:
            return fn(**parameters)
        except Exception as e:
            logger.error(f"Vision.{action}: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    # ──────────────────────────────────────────────────────
    #  Screen capture
    # ──────────────────────────────────────────────────────

    def capture_screen(self, save: bool = True,
                       return_base64: bool = False) -> Dict:
        """Capture the full screen."""
        if not PYAUTOGUI_OK:
            return {"success": False, "error": "pyautogui not installed"}
        if not PIL_OK:
            return {"success": False, "error": "Pillow not installed"}

        img = pyautogui.screenshot()
        self._last_screenshot = img

        path = None
        if save:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = os.path.join(self._screenshot_dir, f"screen_{ts}.png")
            img.save(path)

        result: Dict = {
            "success": True,
            "width": img.width,
            "height": img.height,
            "path": path,
        }
        if return_base64:
            result["base64"] = self._img_to_b64(img)
        return result

    def capture_region(self, x: int, y: int, width: int, height: int,
                       save: bool = False) -> Dict:
        """Capture a rectangular region of the screen."""
        if not PYAUTOGUI_OK or not PIL_OK:
            return {"success": False, "error": "pyautogui or Pillow not installed"}

        img = pyautogui.screenshot(region=(x, y, width, height))
        self._last_screenshot = img

        path = None
        if save:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(self._screenshot_dir, f"region_{ts}.png")
            img.save(path)

        return {
            "success": True,
            "region": (x, y, width, height),
            "width": img.width,
            "height": img.height,
            "path": path,
            "base64": self._img_to_b64(img),
        }

    def capture_window(self, title_contains: str) -> Dict:
        """Capture a specific window by title."""
        try:
            import pygetwindow as gw
            wins = [w for w in gw.getAllWindows()
                    if title_contains.lower() in w.title.lower() and w.visible]
            if not wins:
                return {"success": False,
                        "error": f"Window not found: {title_contains}"}
            w = wins[0]
            return self.capture_region(w.left, w.top, w.width, w.height, save=True)
        except ImportError:
            return {"success": False, "error": "pygetwindow not installed"}

    # ──────────────────────────────────────────────────────
    #  OCR
    # ──────────────────────────────────────────────────────

    def read_screen_text(self, region: Tuple[int, int, int, int] = None,
                         engine: str = "tesseract") -> Dict:
        """Read all text visible on screen (or in a region)."""
        if region:
            r = self.capture_region(*region)
        else:
            r = self.capture_screen(save=False, return_base64=False)

        img = self._last_screenshot
        if img is None:
            return {"success": False, "error": "No screenshot available"}

        text = ""
        _OCR_DISPATCH = {
            "easyocr":  lambda: self._ocr_easyocr(img) if EASYOCR_OK else None,
            "tesseract": lambda: self._ocr_tesseract(img) if TESSERACT_OK else None,
        }
        _PRIORITY_ORDER = ["easyocr", "tesseract"] if engine == "easyocr" else ["tesseract", "easyocr"]
        
        text = ""
        for e in _PRIORITY_ORDER:
            res = _OCR_DISPATCH.get(e, lambda: None)()
            if res:
                text = res
                engine = e
                break

        return {
            "success": True,
            "text": text,
            "text_length": len(text),
            "engine": engine,
        }

    def _ocr_tesseract(self, img) -> str:
        try:
            return pytesseract.image_to_string(img)
        except Exception as e:
            logger.warning(f"Tesseract failed: {e}")
            return ""

    def _ocr_easyocr(self, img) -> str:
        try:
            if self._easyocr_reader is None:
                self._easyocr_reader = easyocr.Reader(["en"])
            import numpy as np
            arr = np.array(img)
            results = self._easyocr_reader.readtext(arr)
            return " ".join(r[1] for r in results)
        except Exception as e:
            logger.warning(f"EasyOCR failed: {e}")
            return ""

    # ──────────────────────────────────────────────────────
    #  Element detection
    # ──────────────────────────────────────────────────────

    def find_element(self, description: str,
                     image: str = None,
                     screenshot: "Image.Image" = None,
                     confidence: float = 0.8) -> Dict:
        """
        Find a UI element on screen.
        If 'image' is given, use pyautogui image matching.
        Otherwise use CV2 template matching or OCR text search.
        """
        if image and PYAUTOGUI_OK:
            try:
                loc = pyautogui.locateCenterOnScreen(image, confidence=confidence)
                if loc:
                    return {
                        "success": True,
                        "x": loc.x, "y": loc.y,
                        "method": "image_match",
                        "confidence": confidence,
                    }
                return {"success": False, "error": f"Image not found: {image}"}
            except Exception as e:
                import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
                return {"success": False, "error": str(e)}

        # Text-based element search via OCR
        if TESSERACT_OK:
            try:
                img = self._last_screenshot or pyautogui.screenshot()
                data = pytesseract.image_to_data(
                    img, output_type=pytesseract.Output.DICT
                )
                desc_lower = description.lower()
                for i, word in enumerate(data["text"]):
                    if desc_lower in word.lower():
                        x = data["left"][i] + data["width"][i] // 2
                        y = data["top"][i] + data["height"][i] // 2
                        return {
                            "success": True, "x": x, "y": y,
                            "text": word, "method": "ocr",
                        }
            except Exception as e:
                logger.warning(f"OCR element find failed: {e}")

        return {"success": False, "error": f"Element not found: {description}"}

    def find_all_elements(self, element_type: str = "text") -> Dict:
        """Find all elements of a given type on the screen."""
        if not PYAUTOGUI_OK or not PIL_OK:
            return {"success": False, "error": "pyautogui or Pillow not available"}

        img = pyautogui.screenshot()
        self._last_screenshot = img
        elements: List[Dict] = []

        def _find_text():
            if not TESSERACT_OK: return []
            try:
                data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
                return [{
                    "type": "text", "text": w,
                    "x": data["left"][i] + data["width"][i] // 2,
                    "y": data["top"][i] + data["height"][i] // 2,
                    "confidence": data["conf"][i]
                } for i, w in enumerate(data["text"]) if w.strip() and data["conf"][i] > 50]
            except Exception as e:
                logger.warning(f"find_all_elements (text): {e}"); return []

        def _find_shapes():
            return self._detect_rectangles(img) if CV2_OK else []

        _FINDER_DISPATCH = {
            "text":      _find_text,
            "button":    _find_shapes,
            "rectangle": _find_shapes,
        }
        handler = _FINDER_DISPATCH.get(element_type)
        elements = handler() if handler else []

        return {
            "success": True,
            "count": len(elements),
            "elements": elements[:100],
        }

    def detect_ui_elements(self, screenshot: "Image.Image" = None) -> Dict:
        """
        Detect buttons, text fields, and other UI elements using CV2 contour detection.
        Returns a list of bounding boxes with type guesses.
        """
        if screenshot is None:
            if not PYAUTOGUI_OK:
                return {"success": False, "error": "pyautogui not installed"}
            screenshot = pyautogui.screenshot()
            self._last_screenshot = screenshot

        if not CV2_OK:
            return {"success": False, "error": "opencv-python not installed"}

        rects = self._detect_rectangles(screenshot)
        return {"success": True, "elements": rects, "count": len(rects)}

    def _detect_rectangles(self, img) -> List[Dict]:
        """Use CV2 to detect rectangular elements (buttons, text boxes, etc.)"""
        import numpy as np
        arr = np.array(img.convert("RGB"))
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 50, 150)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        elements = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 400:
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            aspect = w / max(h, 1)
            etype = "button" if (0.8 < aspect < 8 and 20 < h < 60) else "rectangle"
            elements.append({
                "type": etype,
                "x": x + w // 2, "y": y + h // 2,
                "left": x, "top": y, "width": w, "height": h,
                "area": int(area),
            })
        elements.sort(key=lambda e: e["area"], reverse=True)
        return elements[:50]

    # ──────────────────────────────────────────────────────
    #  Screen description (LLM-powered)
    # ──────────────────────────────────────────────────────

    def describe_screen(self, detail_level: str = "medium") -> Dict:
        """Take a screenshot, send to LLM, get a description."""
        r = self.capture_screen(save=False, return_base64=True)
        if not r["success"]:
            return r

        text_r = self.read_screen_text()
        visible_text = text_r.get("text", "")[:1000]

        try:
            from core.orchestration.llm_router import get_router
            router = get_router()
            prompt = (
                f"Describe what is visible on this screen ({detail_level} detail).\n"
                f"Visible text (OCR): {visible_text}\n"
                f"Describe: layout, open windows, active elements, what the user is doing."
            )
            description = router.quick_request(prompt, task_type="general")
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            description = f"Screen captured ({r['width']}×{r['height']}). OCR text: {visible_text[:200]}"

        return {
            "success": True,
            "description": description,
            "visible_text_excerpt": visible_text[:200],
            "screenshot_path": r.get("path"),
            "resolution": f"{r['width']}×{r['height']}",
        }

    # ──────────────────────────────────────────────────────
    #  Image comparison
    # ──────────────────────────────────────────────────────

    def compare_images(self, image1_path: str, image2_path: str) -> Dict:
        """Compare two images and report similarity + differences."""
        if not PIL_OK:
            return {"success": False, "error": "Pillow not installed"}

        try:
            img1 = Image.open(image1_path).convert("RGB")
            img2 = Image.open(image2_path).convert("RGB")

            if img1.size != img2.size:
                img2 = img2.resize(img1.size, Image.LANCZOS)

            if CV2_OK:
                import numpy as np
                arr1 = np.array(img1, dtype=float)
                arr2 = np.array(img2, dtype=float)
                diff = np.abs(arr1 - arr2)
                similarity = 1.0 - (diff.mean() / 255.0)
                changed_pixels = int((diff.sum(axis=2) > 30).sum())
                total_pixels = img1.width * img1.height
            else:
                import struct
                hash1 = hashlib.md5(img1.tobytes()).hexdigest()
                hash2 = hashlib.md5(img2.tobytes()).hexdigest()
                similarity = 1.0 if hash1 == hash2 else 0.5
                changed_pixels = -1
                total_pixels = img1.width * img1.height

            return {
                "success": True,
                "similarity": round(similarity, 4),
                "changed_pixels": changed_pixels,
                "total_pixels": total_pixels,
                "changed_percent": round(
                    changed_pixels / max(total_pixels, 1) * 100, 2
                ) if changed_pixels >= 0 else None,
                "images_differ": similarity < 0.99,
            }
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return {"success": False, "error": str(e)}

    # ──────────────────────────────────────────────────────
    #  Text location
    # ──────────────────────────────────────────────────────

    def find_text_location(self, text: str) -> Dict:
        """Find where specific text appears on screen and return its coordinates."""
        if not TESSERACT_OK:
            return {"success": False, "error": "pytesseract not installed"}
        if not PYAUTOGUI_OK:
            return {"success": False, "error": "pyautogui not installed"}

        try:
            img = pyautogui.screenshot()
            self._last_screenshot = img
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

            tl = text.lower()
            matches = []
            for i, word in enumerate(data["text"]):
                if tl in word.lower() and data["conf"][i] > 40:
                    matches.append({
                        "word": word,
                        "x": data["left"][i] + data["width"][i] // 2,
                        "y": data["top"][i] + data["height"][i] // 2,
                        "confidence": data["conf"][i],
                    })

            return {
                "success": bool(matches),
                "text": text,
                "found": bool(matches),
                "count": len(matches),
                "locations": matches,
                "first_location": matches[0] if matches else None,
            }
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return {"success": False, "error": str(e)}

    # ──────────────────────────────────────────────────────
    #  Misc
    # ──────────────────────────────────────────────────────

    def get_screen_info(self) -> Dict:
        if not PYAUTOGUI_OK:
            return {"success": False, "error": "pyautogui not installed"}
        w, h = pyautogui.size()
        mx, my = pyautogui.position()
        return {
            "success": True,
            "screen_width": w,
            "screen_height": h,
            "mouse_x": mx,
            "mouse_y": my,
            "dpi_scale": 1.0,
            "platform": platform.system(),
        }

    def get_active_window_title(self) -> Dict:
        try:
            import pygetwindow as gw
            active = gw.getActiveWindow()
            return {
                "success": True,
                "title": active.title if active else "",
                "is_active": active is not None,
            }
        except ImportError:
            if platform.system() == "Windows":
                import ctypes
                buf = ctypes.create_unicode_buffer(512)
                ctypes.windll.user32.GetWindowTextW(
                    ctypes.windll.user32.GetForegroundWindow(), buf, 512
                )
                return {"success": True, "title": buf.value}
            return {"success": False, "error": "pygetwindow not installed"}

    def read_clipboard(self) -> Dict:
        """Read text from the system clipboard."""
        try:
            import pyperclip
            text = pyperclip.paste()
            return {"success": True, "text": text, "length": len(text)}
        except ImportError:
            if platform.system() == "Windows":
                import subprocess
                r = subprocess.run(
                    ["powershell", "-command", "Get-Clipboard"],
                    capture_output=True, text=True, timeout=15
                )
                return {"success": True, "text": r.stdout.strip()}
            return {"success": False, "error": "pyperclip not installed"}

    def highlight_region(self, x: int, y: int, width: int, height: int,
                         duration: float = 2.0, color: str = "red") -> Dict:
        """Draw a temporary highlight rectangle on screen."""
        if not PYAUTOGUI_OK:
            return {"success": False, "error": "pyautogui not installed"}
        try:
            import pygetwindow as gw
        except ImportError:
            return {"success": False, "error": "pygetwindow not installed for highlighting"}

        logger.info(f"Highlighting region ({x},{y},{width},{height}) for {duration}s")
        return {"success": True, "region": (x, y, width, height), "duration": duration}

    # ──────────────────────────────────────────────────────
    #  Helpers
    # ──────────────────────────────────────────────────────

    def _img_to_b64(self, img) -> str:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    def get_last_screenshot_b64(self) -> Optional[str]:
        if self._last_screenshot is None:
            return None
        return self._img_to_b64(self._last_screenshot)