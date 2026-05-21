"""
Browser Agent - Web automation and browser control
Open URLs, search web, extract content, fill forms
"""
import os
import re
import time
import json
import logging
import subprocess
import tempfile
import urllib.request
import urllib.parse
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from html.parser import HTMLParser

from core.base_agent import BaseAgent

logger = logging.getLogger("BrowserAgent")


class TextExtractor(HTMLParser):
    """Extract text from HTML"""
    def __init__(self):
        super().__init__()
        self.texts = []
        self.in_script = False

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.in_script = True

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.in_script = False

    def handle_data(self, data):
        if not self.in_script:
            text = data.strip()
            if text and len(text) > 2:
                self.texts.append(text)

    def get_text(self):
        return '\n'.join(self.texts)


class BrowserAgent(BaseAgent):
    """
    Web browser automation agent.
    Supports basic browsing via webbrowser module and advanced
    automation if Selenium or Playwright are installed.
    """

    def __init__(self):
        super().__init__()
        self.history: List[str] = []
        self.current_url: Optional[str] = None
        self.download_dir = os.path.expanduser("~/Downloads")
        self._selenium_available = self._check_selenium()
        self._playwright_available = self._check_playwright()

        self.handlers = {
            "open_url": self.open_url,
            "search": self.search_web,
            "extract_content": self.extract_content,
            "download": self.download_file,
            "get_page_text": self.get_page_text,
            "find_links": self.find_links,
            "screenshot": self.screenshot_page,
            "fill_form": self.fill_form,
            "click_element": self.click_element,
            "scroll": self.scroll_page,
            "get_title": self.get_page_title,
            "execute_js": self.execute_javascript,
        }

    def _check_selenium(self) -> bool:
        try:
            import selenium
            return True
        except ImportError:
            return False

    def _check_playwright(self) -> bool:
        try:
            import playwright
            return True
        except ImportError:
            return False

    def open_url(self, url: str, wait_time: float = 3.0,
                 browser: str = "default") -> Dict:
        """
        Open URL in browser

        Args:
            url: URL to open
            wait_time: Seconds to wait for load
            browser: Browser to use (chrome, firefox, edge, default)
        """
        try:
            # Add protocol if missing
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url

            self.current_url = url
            self.history.append(url)

            # Use webbrowser module for simple opening
            import webbrowser

            import webbrowser
            
            _get_controller = {
                True:  lambda: webbrowser.get(browser) if browser != "default" else None,
                False: lambda: None
            }
            try:
                browser_controller = _get_controller.get(browser != "default", lambda: None)()
            except:
                browser_controller = None

            _open_fn = {
                True:  lambda: browser_controller.open(url),
                False: lambda: webbrowser.open(url)
            }
            _open_fn[browser_controller is not None]()

            time.sleep(wait_time)

            return {
                "success": True,
                "url": url,
                "browser": browser,
                "history_count": len(self.history)
            }

        except Exception as e:
            # Fallback to os-specific command
            try:
                _OS_OPEN_MAP = {
                    'nt':    lambda: os.system(f'start "" "{url}"'),
                    'posix': lambda: os.system(f'xdg-open "{url}"'),
                }
                _OS_OPEN_MAP.get(os.name, lambda: None)()
                return {"success": True, "url": url, "method": "os_fallback"}
            except Exception as e2:
                return {"success": False, "error": f"{e}; Fallback failed: {e2}"}

    def search_web(self, query: str, engine: str = "duckduckgo",
                   open_result: bool = False) -> Dict:
        """
        Search the web

        Args:
            query: Search query
            engine: Search engine (google, duckduckgo, bing)
            open_result: Whether to open first result
        """
        try:
            # Build search URL
            encoded_query = urllib.parse.quote(query)

            search_urls = {
                "google": f"https://www.google.com/search?q={encoded_query}",
                "duckduckgo": f"https://duckduckgo.com/?q={encoded_query}",
                "bing": f"https://www.bing.com/search?q={encoded_query}",
            }

            search_url = search_urls.get(engine, search_urls["duckduckgo"])

            # Open search
            result = self.open_url(search_url, wait_time=2.0)

            if result.get("success", False):
                # Try to extract results
                try:
                    content = self._fetch_url(search_url)
                    links = self._extract_search_results(content, engine)

                    result["search_engine"] = engine
                    result["query"] = query
                    result["results_found"] = len(links)
                    result["top_results"] = links[:5]

                    if open_result and links:
                        self.open_url(links[0]['url'])

                except Exception as e:
                    logger.warning(f"Could not extract search results: {e}")

            return result

        except Exception as e:
            return {"success": False, "error": str(e)}

    def extract_content(self, url: str = None,
                        selector: str = None) -> Dict:
        """Extract content from webpage"""
        target_url = url or self.current_url
        if not target_url:
            return {"success": False, "error": "No URL specified"}

        try:
            content = self._fetch_url(target_url)

            if selector:
                # Basic selector support without full parser
                content = self._extract_by_selector(content, selector)

            # Extract text
            extractor = TextExtractor()
            try:
                extractor.feed(content)
                text = extractor.get_text()
            except:
                text = re.sub('<[^<]+?>', '', content)  # Fallback strip tags

            # Extract links
            links = self._extract_links(content, target_url)

            return {
                "success": True,
                "url": target_url,
                "title": self._extract_title(content),
                "text": text[:10000],  # Limit output
                "text_length": len(text),
                "links_count": len(links),
                "links": links[:20]
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_page_text(self, url: str = None) -> Dict:
        """Get clean text from webpage"""
        return self.extract_content(url)

    def find_links(self, url: str = None,
                   pattern: str = None) -> Dict:
        """Find links on page matching pattern"""
        target_url = url or self.current_url
        try:
            content = self._fetch_url(target_url)
            links = self._extract_links(content, target_url)

            if pattern:
                regex = re.compile(pattern, re.IGNORECASE)
                links = [l for l in links if regex.search(l['text'] + l['url'])]

            return {
                "success": True,
                "count": len(links),
                "links": links
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def download_file(self, url: str, destination: str = None,
                      filename: str = None) -> Dict:
        """Download file from URL"""
        try:
            if not filename:
                filename = os.path.basename(urllib.parse.urlparse(url).path)
                if not filename:
                    filename = "download"

            if destination:
                filepath = os.path.join(destination, filename)
            else:
                filepath = os.path.join(self.download_dir, filename)

            # Ensure directory exists
            os.makedirs(os.path.dirname(filepath), exist_ok=True)

            # Download
            urllib.request.urlretrieve(url, filepath)

            return {
                "success": True,
                "url": url,
                "filepath": filepath,
                "size": os.path.getsize(filepath)
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def screenshot_page(self, url: str = None,
                        output_path: str = None) -> Dict:
        """Take screenshot of webpage"""
        _SCREENSHOT_DISPATCH = {
            (True,  Any):   lambda: self._screenshot_playwright(url, output_path),
            (False, True):  lambda: self._screenshot_selenium(url, output_path),
            (False, False): lambda: {
                "success": False,
                "error": "No browser automation available.",
                "fallback": "Use vision_system.capture_screen() instead"
            }
        }
        # Determine availability state
        state = (self._playwright_available, self._selenium_available)
        
        # O(1) dispatch via tuple key
        _lookup = {
            True:  lambda: self._screenshot_playwright(url, output_path),
            False: lambda: _SCREENSHOT_DISPATCH.get(state, _SCREENSHOT_DISPATCH[(False, False)])()
        }
        return _lookup[self._playwright_available]()

    def _screenshot_playwright(self, url: str = None,
                                output_path: str = None) -> Dict:
        """Screenshot using Playwright"""
        from playwright.sync_api import sync_playwright

        if not output_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(self.download_dir, f"screenshot_{timestamp}.png")

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={'width': 1920, 'height': 1080})

                target = url or self.current_url or "about:blank"
                page.goto(target, wait_until='networkidle')
                page.screenshot(path=output_path, full_page=True)
                browser.close()

            return {
                "success": True,
                "path": output_path,
                "url": url or self.current_url
            }

        except Exception as e:
            return {"success": False, "error": f"Playwright error: {e}"}

    def _screenshot_selenium(self, url: str = None,
                              output_path: str = None) -> Dict:
        """Screenshot using Selenium"""
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        if not output_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(self.download_dir, f"screenshot_{timestamp}.png")

        try:
            options = Options()
            options.add_argument('--headless')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--window-size=1920,1080')

            driver = webdriver.Chrome(options=options)

            target = url or self.current_url or "about:blank"
            driver.get(target)
            time.sleep(2)

            driver.save_screenshot(output_path)
            driver.quit()

            return {
                "success": True,
                "path": output_path,
                "url": target
            }

        except Exception as e:
            return {"success": False, "error": f"Selenium error: {e}"}

    def fill_form(self, url: str = None, fields: Dict[str, str] = None,
                  submit: bool = False) -> Dict:
        """Fill form fields on webpage"""
        if not self._selenium_available and not self._playwright_available:
            return {"success": False, "error": "Browser automation not available"}

        if self._playwright_available:
            return self._fill_form_playwright(url, fields, submit)

        return {"success": False, "error": "Form filling requires Playwright"}

    def _fill_form_playwright(self, url: str, fields: Dict[str, str],
                               submit: bool) -> Dict:
        """Fill form using Playwright"""
        from playwright.sync_api import sync_playwright

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)
                page = browser.new_page()

                target = url or self.current_url
                page.goto(target, timeout=30000)
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                time.sleep(1.0)   # brief settle after DOM ready

                filled = []
                for selector, value in fields.items():
                    try:
                        # O(1) dict dispatch: strategy → fill callable
                        _FILL_DISPATCH = {
                            'placeholder': lambda p, s, v: p.fill(
                                f'[placeholder="{s}"]', v),
                            'label':       lambda p, s, v: p.get_by_label(s).fill(v),
                            'name':        lambda p, s, v: p.fill(
                                f'[name="{s}"]', v),
                            'id':          lambda p, s, v: p.fill(f'#{s}', v),
                        }
                        _FILL_DEFAULT = lambda p, s, v: p.fill(s, v)
                        for strategy in ['placeholder', 'label', 'name', 'id', 'css']:
                            try:
                                _FILL_DISPATCH.get(
                                    strategy, _FILL_DEFAULT)(page, selector, value)
                                filled.append(selector)
                                break
                            except:
                                continue
                    except Exception as e:
                        logger.warning(f"Could not fill field {selector}: {e}")

                if submit:
                    page.press('body', 'Enter')

                time.sleep(1)
                browser.close()

                return {
                    "success": True,
                    "filled_fields": filled,
                    "total_fields": len(fields)
                }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def click_element(self, selector: str, url: str = None,
                      wait_for: str = "domcontentloaded") -> Dict:
        """Click element on page using Playwright."""
        if self._playwright_available:
            from playwright.sync_api import sync_playwright
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=False)
                    page = browser.new_page()

                    target = url or self.current_url
                    if target:
                        page.goto(target, timeout=30000)
                        page.wait_for_load_state(wait_for, timeout=15000)
                        time.sleep(0.5)

                    # Wait until element is visible before clicking
                    page.wait_for_selector(selector, timeout=10000, state="visible")
                    page.click(selector)
                    time.sleep(0.5)
                    browser.close()

                    return {"success": True, "clicked": selector}
            except Exception as e:
                return {"success": False, "error": str(e)}

        return {"success": False, "error": "Browser automation not available"}

    def scroll_page(self, direction: str = "down", amount: int = 5) -> Dict:
        """
        Scroll the active browser window.

        Args:
            direction: 'down' or 'up'
            amount:    Number of scroll wheel clicks (1 click ≈ 120px). Default 5.
                       Keep this small (3-10); 500 would scroll kilometres.
        """
        try:
            import pyautogui
            clicks = max(1, min(amount, 50))   # cap at 50 to prevent accidents
            # Branchless scroll direction: down → -1, up → +1
            sign = 1 - 2 * (direction == "down")
            pyautogui.scroll(sign * clicks)
            time.sleep(0.15)
            return {"success": True, "direction": direction, "clicks": clicks}
        except ImportError:
            return {"success": False, "error": "pyautogui not available"}

    def get_page_title(self, url: str = None) -> Dict:
        """Get page title"""
        target = url or self.current_url
        try:
            content = self._fetch_url(target)
            title = self._extract_title(content)
            return {"success": True, "title": title, "url": target}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def execute_javascript(self, code: str, url: str = None) -> Dict:
        """Execute JavaScript on page"""
        if self._selenium_available:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options

            try:
                options = Options()
                options.add_argument('--headless')
                driver = webdriver.Chrome(options=options)

                target = url or self.current_url or "about:blank"
                driver.get(target)
                time.sleep(1)

                result = driver.execute_script(code)
                driver.quit()

                return {"success": True, "result": str(result)}

            except Exception as e:
                return {"success": False, "error": str(e)}

        return {"success": False, "error": "Selenium not available"}

    def _fetch_url(self, url: str) -> str:
        """Fetch URL content"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.read().decode('utf-8', errors='replace')

    def _extract_title(self, html: str) -> str:
        """Extract title from HTML"""
        match = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return "No title"

    def _extract_links(self, html: str, base_url: str) -> List[Dict]:
        """Extract all links from HTML"""
        links = []
        seen = set()

        for match in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                                  html, re.DOTALL | re.IGNORECASE):
            url = match.group(1)
            text = re.sub('<[^<]+?>', '', match.group(2)).strip()

            # Resolve relative URLs
            if url.startswith('/'):
                from urllib.parse import urljoin
                url = urljoin(base_url, url)

            if url not in seen and url.startswith('http'):
                seen.add(url)
                links.append({"url": url, "text": text[:100]})

        return links

    def _extract_search_results(self, html: str, engine: str) -> List[Dict]:
        """Extract search results from HTML via O(1) dispatch."""
        results: List[Dict] = []

        def _parse_ddg():
            for match in re.finditer(r'<a[^>]+class="result__a"[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.DOTALL | re.IGNORECASE):
                results.append({"url": match.group(1), "title": re.sub('<[^<]+?>', '', match.group(2)).strip()})

        def _parse_google():
            for match in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.DOTALL | re.IGNORECASE):
                url = match.group(1)
                if url.startswith('/url?'):
                    um = re.search(r'[?&]url=([^&]+)', url)
                    if um: url = urllib.parse.unquote(um.group(1))
                if url.startswith('http'):
                    results.append({"url": url, "title": re.sub('<[^<]+?>', '', match.group(2)).strip()})

        _PARSER_DISPATCH = {"duckduckgo": _parse_ddg, "google": _parse_google}
        handler = _PARSER_DISPATCH.get(engine.lower())
        handler() if handler else None
        return results[:10]

    def _extract_by_selector(self, html: str, selector: str) -> str:
        """Basic selector extraction via O(1) prefix dispatch."""
        def _by_id(sel):
            m = re.search(f'<[^>]+id=["\']{sel[1:]}["\'][^>]*>(.*?)</[^>]+>', html, re.DOTALL | re.IGNORECASE)
            return m.group(1) if m else html

        def _by_class(sel):
            m = re.search(f'<[^>]+class=["\'][^"\']*{sel[1:]}[^"\']*["\'][^>]*>(.*?)</[^>]+>', html, re.DOTALL | re.IGNORECASE)
            return m.group(1) if m else html

        _PREFIX_DISPATCH = {"#": _by_id, ".": _by_class}
        handler = _PREFIX_DISPATCH.get(selector[0] if selector else "")
        return handler(selector) if handler else html

    def get_history(self) -> List[str]:
        """Get browsing history"""
        return self.history