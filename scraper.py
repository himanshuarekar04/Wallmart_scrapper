"""
scraper.py
----------
Core HTTP fetching module using curl_cffi to impersonate a real Chrome browser,
bypassing Walmart's TLS fingerprint-based bot detection (Akamai / PerimeterX).

Compatible with curl_cffi >= 0.7.x and >= 0.15.x
"""

import os
import json
import logging
import random
import time
import urllib.parse
from typing import Optional

from bs4 import BeautifulSoup
import curl_cffi
from curl_cffi import requests as cffi_requests

logger = logging.getLogger(__name__)

# Load proxy URL from environment variables if present
WALMART_PROXY_URL = os.environ.get("WALMART_PROXY_URL")

def _get_curl_proxies() -> Optional[dict]:
    """Return a proxies dict for curl_cffi if WALMART_PROXY_URL is set."""
    if not WALMART_PROXY_URL:
        return None
    return {
        "http": WALMART_PROXY_URL,
        "https": WALMART_PROXY_URL,
    }

def _get_playwright_proxy() -> Optional[dict]:
    """Parse WALMART_PROXY_URL into a Playwright compatible proxy dict."""
    if not WALMART_PROXY_URL:
        return None
    try:
        parsed = urllib.parse.urlparse(WALMART_PROXY_URL)
        proxy_config = {
            "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
        }
        if parsed.username and parsed.password:
            proxy_config["username"] = parsed.username
            proxy_config["password"] = parsed.password
        return proxy_config
    except Exception as e:
        logger.error(f"Failed to parse WALMART_PROXY_URL for Playwright: {e}")
        return None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WALMART_BASE = "https://www.walmart.com"

# Rotate through a few realistic Chrome UA strings
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

_BASE_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "accept-encoding": "gzip, deflate, br",
    "cache-control": "no-cache",
    "pragma": "no-cache",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "referer": "https://www.walmart.com/",
}

# ---------------------------------------------------------------------------
# Session (reused across requests for cookie/header persistence)
# ---------------------------------------------------------------------------

def _build_session() -> cffi_requests.Session:
    """Create a curl_cffi session that impersonates Chrome.

    curl_cffi >= 0.15 changed the Session constructor; impersonate is passed
    per-request via .get() instead.  We detect the version and adapt.
    """
    try:
        # v0.15+ style
        session = cffi_requests.Session()
    except Exception:
        session = cffi_requests.Session(impersonate="chrome124")
    session.headers.update(_BASE_HEADERS)
    session.headers["user-agent"] = random.choice(_USER_AGENTS)
    return session


# Pick the right impersonate kwarg based on curl_cffi version
def _get_impersonate_kwarg() -> dict:
    ver = tuple(int(x) for x in curl_cffi.__version__.split(".")[:2])
    if ver >= (0, 15):
        return {"impersonate": "chrome"}
    return {"impersonate": "chrome124"}



def fetch_product_page_playwright(url: str) -> Optional[str]:
    """
    Fallback browser fetcher using Playwright.
    Launches Chromium headlessly to load the page and wait for __NEXT_DATA__.
    """
    from playwright.sync_api import sync_playwright

    logger.info(f"Launching Playwright fallback for URL: {url}")
    try:
        with sync_playwright() as p:
            # Emulate realistic device viewport & user agent
            playwright_proxy = _get_playwright_proxy()
            if playwright_proxy:
                logger.info(f"Playwright: routing traffic through proxy: {playwright_proxy.get('server')}")
            browser = p.chromium.launch(headless=True, proxy=playwright_proxy)
            context = browser.new_context(
                user_agent=random.choice(_USER_AGENTS),
                viewport={"width": 1280, "height": 720},
                ignore_https_errors=True,
                extra_http_headers={
                    "referer": "https://www.walmart.com/",
                    "sec-fetch-site": "same-origin",
                    "accept-language": "en-US,en;q=0.9",
                }
            )
            page = context.new_page()

            # Go to product URL and wait for page to hydrate/render
            logger.info("Playwright: navigating to page...")
            page.goto(url, timeout=30000, wait_until="domcontentloaded")

            # Look for __NEXT_DATA__ in the page source
            try:
                # Wait for script tag to render
                page.wait_for_selector("script#__NEXT_DATA__", timeout=10000)
            except Exception:
                logger.warning("Playwright: __NEXT_DATA__ script tag not found within timeout.")

            content = page.content()
            browser.close()

            if "__NEXT_DATA__" in content:
                logger.info(f"Playwright successfully fetched page data (size={len(content)} bytes)")
                return content
            else:
                logger.error("Playwright: page loaded but missing __NEXT_DATA__")
                return None
    except Exception as exc:
        logger.error(f"Playwright scraping exception: {exc}")
        return None


# ---------------------------------------------------------------------------
# Public fetch helpers
# ---------------------------------------------------------------------------

def fetch_product_page(url: str, retries: int = 3) -> Optional[str]:
    """
    Fetch a Walmart product page HTML.

    Returns the HTML string on success, or None if all retries fail.
    Implements simple exponential back-off between attempts.
    """
    session = _build_session()
    proxies = _get_curl_proxies()
    if proxies:
        logger.info(f"curl_cffi: routing traffic through proxy: {WALMART_PROXY_URL}")
        session.proxies = proxies

    imp_kwarg = _get_impersonate_kwarg()

    for attempt in range(1, retries + 1):
        try:
            logger.info(f"[Attempt {attempt}/{retries}] GET {url}")
            verify_ssl = False if WALMART_PROXY_URL else True
            resp = session.get(url, timeout=30, allow_redirects=True, verify=verify_ssl, **imp_kwarg)

            if resp.status_code in (200, 404) and "__NEXT_DATA__" in resp.text:
                if resp.status_code != 200:
                    logger.warning(f"Received non-200 status code ({resp.status_code}) but found __NEXT_DATA__; continuing.")
                logger.info(f"Successfully fetched page (size={len(resp.text)} bytes)")
                return resp.text
            else:
                logger.warning(f"Response failed verification — status={resp.status_code}, contains NEXT_DATA={'__NEXT_DATA__' in resp.text}. Treating as block/invalid URL.")

        except Exception as exc:
            logger.error(f"Request error on attempt {attempt}: {exc}")

        # Back-off before retry (2s, 4s, 8s …)
        sleep_time = 2 ** attempt
        logger.info(f"Retrying in {sleep_time}s …")
        time.sleep(sleep_time)

    logger.warning(f"All {retries} curl_cffi attempts failed or got blocked for URL: {url}. Initiating Playwright fallback...")
    try:
        html = fetch_product_page_playwright(url)
        if html:
            return html
    except Exception as e:
        logger.error(f"Playwright fallback error: {e}")

    return None


def fetch_search_page(query: str, retries: int = 3) -> Optional[str]:
    """
    Fetch Walmart search results page HTML for a given query string.
    """
    search_url = f"{WALMART_BASE}/search?q={urllib.parse.quote(query)}&typeahead=true"
    return fetch_product_page(search_url, retries=retries)


def extract_next_data(html: str) -> Optional[dict]:
    """
    Parse the __NEXT_DATA__ JSON blob from a Walmart page HTML string.
    Returns the parsed dict, or None if not found / invalid JSON.
    """
    try:
        soup = BeautifulSoup(html, "lxml")
        tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if not tag or not tag.string:
            logger.error("__NEXT_DATA__ script tag not found in HTML")
            return None
        data = json.loads(tag.string)
        logger.debug("__NEXT_DATA__ parsed successfully")
        return data
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error parsing __NEXT_DATA__: {e}")
        return None
