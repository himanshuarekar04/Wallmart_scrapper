"""
search.py
---------
Performs a Walmart keyword search and extracts the first matching item ID,
which is then used to construct the full product URL for scraping.
"""

import logging
import re
from typing import Optional

from scraper import extract_next_data, fetch_search_page

logger = logging.getLogger(__name__)

# Regex fallback: extract first usItemId from raw HTML
_ITEM_ID_RE = re.compile(r'"usItemId"\s*:\s*"(\d+)"')


def search_item_id(query: str) -> Optional[str]:
    """
    Search Walmart for `query` and return the first result's item ID.

    Strategy:
      1. Fetch search results page HTML
      2. Parse __NEXT_DATA__ → navigate to search results list
      3. Return usItemId of first result
      4. Fallback: regex scan for first usItemId in raw HTML
    """
    logger.info(f"Searching Walmart for: '{query}'")
    html = fetch_search_page(query)
    if not html:
        logger.error("Failed to fetch search page")
        return None

    # ── Strategy 1: __NEXT_DATA__ structured parse ──────────────────────────
    next_data = extract_next_data(html)
    if next_data:
        item_id = _parse_search_next_data(next_data)
        if item_id:
            logger.info(f"Found item ID via __NEXT_DATA__: {item_id}")
            return item_id

    # ── Strategy 2: regex fallback ───────────────────────────────────────────
    match = _ITEM_ID_RE.search(html)
    if match:
        item_id = match.group(1)
        logger.info(f"Found item ID via regex fallback: {item_id}")
        return item_id

    logger.error("Could not extract any item ID from search results")
    return None


def _parse_search_next_data(next_data: dict) -> Optional[str]:
    """
    Navigate __NEXT_DATA__ search response to find the first product's item ID.
    Tries multiple known paths since Walmart's structure may vary.
    """
    try:
        # Path 1: initialData → searchResult → itemStacks → items
        initial_data = (
            next_data
            .get("props", {})
            .get("pageProps", {})
            .get("initialData", {})
        )
        search_result = initial_data.get("searchResult", {})
        item_stacks   = search_result.get("itemStacks", [])

        for stack in item_stacks:
            items = stack.get("items", [])
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_id = item.get("usItemId") or item.get("itemId")
                if item_id:
                    return str(item_id)

        # Path 2: contentLayout → modules → items (alternate structure)
        content_layout = initial_data.get("contentLayout", {})
        for module in (content_layout.get("modules") or []):
            if not isinstance(module, dict):
                continue
            for item in (module.get("items") or []):
                if not isinstance(item, dict):
                    continue
                item_id = item.get("usItemId") or item.get("itemId")
                if item_id:
                    return str(item_id)

    except Exception as exc:
        logger.error(f"Error parsing search __NEXT_DATA__: {exc}")

    return None
