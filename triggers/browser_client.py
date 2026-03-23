"""
Sentinel AI — Browser Client (BROWSER-1)
Dual-mode web content fetcher:
  - Simple mode: httpx + BeautifulSoup for static pages (free, fast)
  - Browser mode: Browser-Use Cloud API for JS-rendered / interactive pages

Singleton pattern matching rss_client.py / todoist_client.py.
"""
import hashlib
import logging
import time
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
        cdp_url = config.browser.chrome_cdp_url
        if not cdp_url:
            return {"content": "", "title": "", "content_hash": "", "error": "CHROME_CDP_URL not configured"}

        cdp_base = cdp_url.rstrip("/")
        self._rate_limit()

        try:
            # 1. Get list of tabs, find or create a worker tab
            resp = self._httpx_client.get(f"{cdp_base}/json/list", timeout=10)
            resp.raise_for_status()
            tabs = resp.json()
            page_tabs = [t for t in tabs if t.get("type") == "page"]

            # Use existing tab or create new one
            if page_tabs:
                tab_ws = page_tabs[0].get("webSocketDebuggerUrl", "")
                tab_id = page_tabs[0].get("id", "")
            else:
                return {"content": "", "title": "", "content_hash": "", "error": "No Chrome tabs available"}

            # 2. Connect via WebSocket and navigate
            import websocket as ws_lib
            import json as _json

            # Build WebSocket URL through the Funnel proxy
            ws_url = f"{cdp_base.replace('https://', 'wss://').replace('http://', 'ws://')}/devtools/page/{tab_id}"

            conn = ws_lib.create_connection(ws_url, timeout=15)

            # Navigate
            conn.send(_json.dumps({
                "id": 1, "method": "Page.navigate",
                "params": {"url": url}
            }))
            conn.recv()  # navigation response

            # Wait for page load
            time.sleep(wait_seconds)

            # 3. Extract page content via DOM
            conn.send(_json.dumps({
                "id": 2, "method": "Runtime.evaluate",
                "params": {"expression": "document.title"}
            }))
            title_resp = _json.loads(conn.recv())
            title = title_resp.get("result", {}).get("result", {}).get("value", "")

            conn.send(_json.dumps({
                "id": 3, "method": "Runtime.evaluate",
                "params": {"expression": "document.body.innerText"}
            }))
            body_resp = _json.loads(conn.recv())
            content = body_resp.get("result", {}).get("result", {}).get("value", "")
            content = content[:10000] if content else ""  # Cap at 10K

            conn.close()

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
        cdp_url = config.browser.chrome_cdp_url
        if not cdp_url:
            return []
        try:
            resp = self._httpx_client.get(f"{cdp_url.rstrip('/')}/json/list", timeout=10)
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
