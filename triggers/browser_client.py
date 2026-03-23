"""
Sentinel AI — Browser Client (BROWSER-1 + Phase 3)
Dual-mode web content fetcher + interactive browser actions:
  - Simple mode: httpx + BeautifulSoup for static pages (free, fast)
  - Browser mode: Browser-Use Cloud API for JS-rendered / interactive pages
  - Chrome CDP mode: read + interact via Tailscale Funnel to Director's machine

Singleton pattern matching rss_client.py / todoist_client.py.
"""
import base64
import hashlib
import json as _json
import logging
import time
from contextlib import contextmanager
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from config.settings import config

logger = logging.getLogger("sentinel.browser_client")

_USER_AGENT = "Baker-AI/1.0 (Browser Sentinel)"


class BrowserClient:
    """Dual-mode browser client — simple HTTP + Browser-Use Cloud."""

    _instance = None

    @classmethod
    def _get_global_instance(cls):
        """Return the module-level singleton. Lazy-init if needed."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._httpx_client = httpx.Client(
            timeout=config.browser.simple_timeout,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        )
        self._cloud_api_key = config.browser.cloud_api_key
        self._cloud_base_url = config.browser.cloud_base_url.rstrip("/")
        self._last_request_time = 0.0

    # -------------------------------------------------------
    # Simple mode: httpx + BeautifulSoup
    # -------------------------------------------------------

    def fetch_simple(self, url: str, css_selectors: dict = None) -> dict:
        """Fetch a static page via HTTP and extract text.

        Args:
            url: Page URL to fetch.
            css_selectors: Optional dict of {label: css_selector} to extract
                           specific elements. If None, extracts full page text.

        Returns:
            {content: str, title: str, extracted: dict, content_hash: str}
        """
        self._rate_limit()

        try:
            resp = self._httpx_client.get(url)
            resp.raise_for_status()
        except httpx.TimeoutException:
            logger.warning(f"Timeout fetching {url}")
            return {"content": "", "title": "", "extracted": {}, "content_hash": "", "error": "timeout"}
        except httpx.HTTPStatusError as e:
            logger.warning(f"HTTP {e.response.status_code} fetching {url}")
            return {"content": "", "title": "", "extracted": {}, "content_hash": "", "error": f"http_{e.response.status_code}"}
        except Exception as e:
            logger.warning(f"Error fetching {url}: {e}")
            return {"content": "", "title": "", "extracted": {}, "content_hash": "", "error": str(e)}

        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove script/style elements
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        full_text = soup.get_text(separator="\n", strip=True)

        # Extract specific elements if selectors provided
        extracted = {}
        if css_selectors:
            for label, selector in css_selectors.items():
                elements = soup.select(selector)
                extracted[label] = [el.get_text(strip=True) for el in elements]

        # Use extracted text if selectors provided, otherwise full page
        content = ""
        if extracted:
            for label, values in extracted.items():
                content += f"[{label}]\n" + "\n".join(values) + "\n\n"
            content = content.strip()
        else:
            content = full_text[:10000]  # Cap at 10K chars

        return {
            "content": content,
            "title": title,
            "extracted": extracted,
            "content_hash": self.content_hash(content),
        }

    # -------------------------------------------------------
    # Browser mode: Browser-Use Cloud API
    # -------------------------------------------------------

    def run_browser_task(self, task_prompt: str, url: str) -> dict:
        """Submit task to Browser-Use Cloud API and wait for result.

        Args:
            task_prompt: Natural language instruction (e.g., "Extract room rates")
            url: Starting URL for the browser task.

        Returns:
            {content: str, content_hash: str, steps: int, status: str, error: str|None}
        """
        if not self._cloud_api_key:
            return {
                "content": "",
                "content_hash": "",
                "steps": 0,
                "status": "error",
                "error": "BROWSER_USE_API_KEY not configured",
            }

        self._rate_limit()

        # 1. Create task
        full_prompt = f"Go to {url} and {task_prompt}"
        try:
            create_resp = self._httpx_client.post(
                f"{self._cloud_base_url}/tasks",
                headers={
                    "Authorization": f"Bearer {self._cloud_api_key}",
                    "Content-Type": "application/json",
                },
                json={"task": full_prompt},
                timeout=30,
            )
            create_resp.raise_for_status()
            task_data = create_resp.json()
            task_id = task_data.get("id")
        except Exception as e:
            logger.error(f"Browser-Use task creation failed: {e}")
            return {
                "content": "",
                "content_hash": "",
                "steps": 0,
                "status": "error",
                "error": f"Task creation failed: {e}",
            }

        if not task_id:
            return {
                "content": "",
                "content_hash": "",
                "steps": 0,
                "status": "error",
                "error": "No task_id returned from Browser-Use API",
            }

        # 2. Poll for completion
        timeout_s = config.browser.browser_timeout
        poll_interval = 3  # seconds
        elapsed = 0

        while elapsed < timeout_s:
            time.sleep(poll_interval)
            elapsed += poll_interval

            try:
                status_resp = self._httpx_client.get(
                    f"{self._cloud_base_url}/tasks/{task_id}",
                    headers={"Authorization": f"Bearer {self._cloud_api_key}"},
                    timeout=15,
                )
                status_resp.raise_for_status()
                status_data = status_resp.json()
            except Exception as e:
                logger.warning(f"Browser-Use status poll failed: {e}")
                continue

            status = status_data.get("status", "")
            if status in ("finished", "completed", "done"):
                output = status_data.get("output", "") or status_data.get("result", "")
                if isinstance(output, dict):
                    output = str(output)
                content = str(output)[:10000]
                return {
                    "content": content,
                    "content_hash": self.content_hash(content),
                    "steps": status_data.get("steps", 0),
                    "status": "finished",
                    "error": None,
                }
            elif status in ("failed", "stopped", "error"):
                error_msg = status_data.get("error", "Task failed")
                logger.warning(f"Browser-Use task {task_id} failed: {error_msg}")
                return {
                    "content": "",
                    "content_hash": "",
                    "steps": status_data.get("steps", 0),
                    "status": status,
                    "error": str(error_msg),
                }

        # Timeout
        logger.warning(f"Browser-Use task {task_id} timed out after {timeout_s}s")
        return {
            "content": "",
            "content_hash": "",
            "steps": 0,
            "status": "timeout",
            "error": f"Task timed out after {timeout_s}s",
        }

    # -------------------------------------------------------
    # Chrome CDP mode: via Tailscale Funnel to Mac Mini
    # -------------------------------------------------------

    def _get_cdp_base(self) -> Optional[str]:
        """Return the CDP base URL or None if not configured."""
        cdp_url = config.browser.chrome_cdp_url
        return cdp_url.rstrip("/") if cdp_url else None

    def _get_first_tab_id(self, cdp_base: str) -> Optional[str]:
        """Get the ID of the first page-type tab."""
        resp = self._httpx_client.get(f"{cdp_base}/json/list", timeout=10)
        resp.raise_for_status()
        tabs = resp.json()
        page_tabs = [t for t in tabs if t.get("type") == "page"]
        return page_tabs[0]["id"] if page_tabs else None

    @contextmanager
    def _cdp_connection(self, tab_id: str = None):
        """Context manager for a CDP WebSocket connection.

        Yields (conn, msg_id_counter) where conn is the WebSocket and
        msg_id_counter is a mutable list [next_id] for tracking CDP message IDs.
        """
        import websocket as ws_lib

        cdp_base = self._get_cdp_base()
        if not cdp_base:
            raise RuntimeError("CHROME_CDP_URL not configured")

        if not tab_id:
            tab_id = self._get_first_tab_id(cdp_base)
        if not tab_id:
            raise RuntimeError("No Chrome tabs available")

        ws_url = f"{cdp_base.replace('https://', 'wss://').replace('http://', 'ws://')}/devtools/page/{tab_id}"
        conn = ws_lib.create_connection(ws_url, timeout=15)
        msg_id = [1]  # mutable counter

        try:
            yield conn, msg_id
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _cdp_send(self, conn, msg_id: list, method: str, params: dict = None) -> dict:
        """Send a CDP command and return the response."""
        cmd = {"id": msg_id[0], "method": method}
        if params:
            cmd["params"] = params
        msg_id[0] += 1
        conn.send(_json.dumps(cmd))
        return _json.loads(conn.recv())

    def _cdp_evaluate(self, conn, msg_id: list, expression: str) -> dict:
        """Evaluate JS expression via CDP and return the full result object."""
        resp = self._cdp_send(conn, msg_id, "Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        })
        return resp.get("result", {}).get("result", {})

    def fetch_chrome(self, url: str, wait_seconds: int = 3) -> dict:
        """Navigate Chrome to a URL via CDP and extract page content.

        Uses the Chrome DevTools Protocol through Tailscale Funnel.
        Chrome runs on Mac Mini with authenticated sessions (WhatsApp, Gmail, etc.)

        Args:
            url: URL to navigate to.
            wait_seconds: Seconds to wait after navigation for page to load.

        Returns:
            {content: str, title: str, content_hash: str, error: str|None}
        """
        cdp_base = self._get_cdp_base()
        if not cdp_base:
            return {"content": "", "title": "", "content_hash": "", "error": "CHROME_CDP_URL not configured"}

        self._rate_limit()

        try:
            with self._cdp_connection() as (conn, msg_id):
                # Navigate
                self._cdp_send(conn, msg_id, "Page.navigate", {"url": url})
                time.sleep(wait_seconds)

                # Extract page content
                title_result = self._cdp_evaluate(conn, msg_id, "document.title")
                title = title_result.get("value", "")

                body_result = self._cdp_evaluate(conn, msg_id, "document.body.innerText")
                content = body_result.get("value", "")
                content = content[:10000] if content else ""

            return {
                "content": content,
                "title": title,
                "content_hash": self.content_hash(content),
                "error": None,
            }
        except Exception as e:
            logger.error(f"Chrome CDP fetch failed for {url}: {e}")
            return {"content": "", "title": "", "content_hash": "", "error": str(e)}

    def list_chrome_tabs(self) -> list:
        """List open Chrome tabs via CDP.

        Returns:
            List of {id, title, url} dicts for page-type tabs.
        """
        cdp_base = self._get_cdp_base()
        if not cdp_base:
            return []
        try:
            resp = self._httpx_client.get(f"{cdp_base}/json/list", timeout=10)
            resp.raise_for_status()
            return [
                {"id": t["id"], "title": t.get("title", ""), "url": t.get("url", "")}
                for t in resp.json()
                if t.get("type") == "page"
            ]
        except Exception as e:
            logger.warning(f"Chrome tab list failed: {e}")
            return []

    # -------------------------------------------------------
    # Chrome CDP: Interactive actions (Phase 3)
    # -------------------------------------------------------

    def take_screenshot(self, format: str = "png", quality: int = 80) -> dict:
        """Capture a screenshot of the current Chrome page.

        Args:
            format: 'png' or 'jpeg'
            quality: JPEG quality (1-100), ignored for PNG

        Returns:
            {data_b64: str, format: str, error: str|None}
        """
        try:
            with self._cdp_connection() as (conn, msg_id):
                params = {"format": format}
                if format == "jpeg":
                    params["quality"] = quality
                resp = self._cdp_send(conn, msg_id, "Page.captureScreenshot", params)
                data = resp.get("result", {}).get("data", "")
                if not data:
                    return {"data_b64": "", "format": format, "error": "No screenshot data returned"}
                return {"data_b64": data, "format": format, "error": None}
        except Exception as e:
            logger.error(f"take_screenshot failed: {e}")
            return {"data_b64": "", "format": format, "error": str(e)}

    def click_element(self, selector: str) -> dict:
        """Click an element on the current page by CSS selector.

        Uses JS-based click (element.click()) which works for most elements.

        Args:
            selector: CSS selector (e.g. 'button.add-to-cart', '#submit-btn')

        Returns:
            {success: bool, element_text: str, error: str|None}
        """
        self._rate_limit()
        try:
            with self._cdp_connection() as (conn, msg_id):
                js = f"""
                (() => {{
                    const el = document.querySelector({_json.dumps(selector)});
                    if (!el) return {{success: false, error: 'Element not found', text: ''}};
                    const text = el.innerText || el.textContent || el.value || '';
                    el.click();
                    return {{success: true, error: null, text: text.substring(0, 200)}};
                }})()
                """
                result = self._cdp_evaluate(conn, msg_id, js)
                val = result.get("value", {})
                if isinstance(val, dict):
                    return {
                        "success": val.get("success", False),
                        "element_text": val.get("text", ""),
                        "error": val.get("error"),
                    }
                return {"success": False, "element_text": "", "error": "Unexpected response"}
        except Exception as e:
            logger.error(f"click_element failed: {e}")
            return {"success": False, "element_text": "", "error": str(e)}

    def click_by_text(self, text: str, tag: str = None) -> dict:
        """Click an element by its visible text content.

        Searches all clickable elements (a, button, input[type=submit], [role=button])
        for text match. Optional tag filter.

        Args:
            text: Visible text to match (case-insensitive substring)
            tag: Optional HTML tag to restrict search (e.g. 'button', 'a')

        Returns:
            {success: bool, element_text: str, selector: str, error: str|None}
        """
        self._rate_limit()
        try:
            with self._cdp_connection() as (conn, msg_id):
                js = f"""
                (() => {{
                    const searchText = {_json.dumps(text)}.toLowerCase();
                    const tagFilter = {_json.dumps(tag or '')}.toLowerCase();
                    const candidates = document.querySelectorAll(
                        'a, button, input[type="submit"], input[type="button"], [role="button"], [onclick]'
                    );
                    for (const el of candidates) {{
                        if (tagFilter && el.tagName.toLowerCase() !== tagFilter) continue;
                        const elText = (el.innerText || el.textContent || el.value || '').trim();
                        if (elText.toLowerCase().includes(searchText)) {{
                            el.click();
                            return {{
                                success: true, error: null,
                                text: elText.substring(0, 200),
                                selector: el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (el.className ? '.' + el.className.split(' ')[0] : '')
                            }};
                        }}
                    }}
                    return {{success: false, error: 'No clickable element found with text: ' + searchText, text: '', selector: ''}};
                }})()
                """
                result = self._cdp_evaluate(conn, msg_id, js)
                val = result.get("value", {})
                if isinstance(val, dict):
                    return {
                        "success": val.get("success", False),
                        "element_text": val.get("text", ""),
                        "selector": val.get("selector", ""),
                        "error": val.get("error"),
                    }
                return {"success": False, "element_text": "", "selector": "", "error": "Unexpected response"}
        except Exception as e:
            logger.error(f"click_by_text failed: {e}")
            return {"success": False, "element_text": "", "selector": "", "error": str(e)}

    def fill_field(self, selector: str, value: str) -> dict:
        """Fill a form field on the current page.

        Sets value and dispatches input/change events for reactivity.

        Args:
            selector: CSS selector for the input/textarea element
            value: Text value to set

        Returns:
            {success: bool, previous_value: str, error: str|None}
        """
        self._rate_limit()
        try:
            with self._cdp_connection() as (conn, msg_id):
                js = f"""
                (() => {{
                    const el = document.querySelector({_json.dumps(selector)});
                    if (!el) return {{success: false, prev: '', error: 'Element not found'}};
                    const prev = el.value || '';
                    // Use native input setter to trigger React/Vue reactivity
                    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    )?.set || Object.getOwnPropertyDescriptor(
                        window.HTMLTextAreaElement.prototype, 'value'
                    )?.set;
                    if (nativeInputValueSetter) {{
                        nativeInputValueSetter.call(el, {_json.dumps(value)});
                    }} else {{
                        el.value = {_json.dumps(value)};
                    }}
                    el.dispatchEvent(new Event('input', {{bubbles: true}}));
                    el.dispatchEvent(new Event('change', {{bubbles: true}}));
                    return {{success: true, prev: prev.substring(0, 200), error: null}};
                }})()
                """
                result = self._cdp_evaluate(conn, msg_id, js)
                val = result.get("value", {})
                if isinstance(val, dict):
                    return {
                        "success": val.get("success", False),
                        "previous_value": val.get("prev", ""),
                        "error": val.get("error"),
                    }
                return {"success": False, "previous_value": "", "error": "Unexpected response"}
        except Exception as e:
            logger.error(f"fill_field failed: {e}")
            return {"success": False, "previous_value": "", "error": str(e)}

    def get_page_info(self) -> dict:
        """Get current page URL, title, and form elements summary.

        Returns:
            {url: str, title: str, forms: list, clickable: list, error: str|None}
        """
        try:
            with self._cdp_connection() as (conn, msg_id):
                js = """
                (() => {
                    const forms = [];
                    document.querySelectorAll('input, textarea, select').forEach(el => {
                        if (el.type === 'hidden') return;
                        forms.push({
                            tag: el.tagName.toLowerCase(),
                            type: el.type || '',
                            name: el.name || '',
                            id: el.id || '',
                            placeholder: el.placeholder || '',
                            value: (el.value || '').substring(0, 50)
                        });
                    });
                    const clickable = [];
                    document.querySelectorAll('a, button, input[type="submit"], [role="button"]').forEach(el => {
                        const text = (el.innerText || el.textContent || el.value || '').trim();
                        if (!text || text.length > 100) return;
                        clickable.push({
                            tag: el.tagName.toLowerCase(),
                            text: text.substring(0, 100),
                            href: el.href || '',
                            id: el.id || ''
                        });
                    });
                    return {
                        url: window.location.href,
                        title: document.title,
                        forms: forms.slice(0, 30),
                        clickable: clickable.slice(0, 50)
                    };
                })()
                """
                result = self._cdp_evaluate(conn, msg_id, js)
                val = result.get("value", {})
                if isinstance(val, dict):
                    val["error"] = None
                    return val
                return {"url": "", "title": "", "forms": [], "clickable": [], "error": "Unexpected response"}
        except Exception as e:
            logger.error(f"get_page_info failed: {e}")
            return {"url": "", "title": "", "forms": [], "clickable": [], "error": str(e)}

    # -------------------------------------------------------
    # Helpers
    # -------------------------------------------------------

    @staticmethod
    def content_hash(content: str) -> str:
        """SHA-256 hash of content for change detection."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _rate_limit(self):
        """Enforce max 1 request per second to be polite to target hosts."""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        self._last_request_time = time.time()
