"""
main.py
-------
FastAPI application exposing three live Walmart product data endpoints.
Designed for Postman-based client testing (POC stage).

Endpoints
---------
GET /api/product/by-id/{item_id}     — Fetch by Walmart item ID
GET /api/product/by-url              — Fetch by full Walmart product URL  (?url=...)
GET /api/product/by-name             — Fetch by product name search       (?q=...)
GET /health                          — Health check
"""

import logging
import re
import sys
import time
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from parser import parse_product
from scraper import WALMART_BASE, extract_next_data, fetch_product_page
from search import search_item_id

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("walmart_api")

# ---------------------------------------------------------------------------
# App initialisation
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Walmart U.S. Live Product Scraper API",
    description=(
        "Fetch real-time product data from Walmart U.S. by item ID, product URL, "
        "or product name. POC build — no proxy, US default location."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_response(item: Optional[dict], error: Optional[str] = None) -> dict:
    """Wrap the parsed item in the standardised envelope."""
    return {
        "bff_meta":  None,
        "error":     None if not error else "SCRAPER_ERROR",
        "error_msg": error,
        "data": {
            "item": item,
        } if not error else None,
    }


def _scrape_by_url(url: str) -> dict:
    """Core pipeline: fetch → extract → parse → wrap."""
    start = time.perf_counter()
    logger.info(f"Scraping URL: {url}")

    html = fetch_product_page(url)
    if not html:
        return _build_response(None, "Failed to fetch the product page. Walmart may have blocked the request.")

    next_data = extract_next_data(html)
    if not next_data:
        return _build_response(None, "Could not parse __NEXT_DATA__ from the page. Page structure may have changed.")

    item = parse_product(next_data)
    if not item:
        return _build_response(None, "Product data not found in the parsed response.")

    elapsed = round(time.perf_counter() - start, 2)
    logger.info(f"Scrape completed in {elapsed}s for item_id={item.get('item_id')}")
    return _build_response(item)


def _validate_walmart_url(url: str) -> bool:
    """Basic sanity-check that the URL points to a Walmart product page."""
    return bool(
        re.match(r"https?://(www\.)?walmart\.com/ip/", url)
    )


def _item_id_to_url(item_id: str) -> str:
    # Walmart /ip/{id} alone 404s; /ip/product/{id} is a valid redirect-friendly format
    return f"{WALMART_BASE}/ip/product/{item_id}"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", tags=["System"])
def health_check():
    """Simple liveness probe."""
    return {"status": "ok", "service": "walmart-scraper-poc"}


@app.get(
    "/api/product/by-id/{item_id}",
    tags=["Product"],
    summary="Fetch product by Walmart Item ID",
    response_description="Live product data from Walmart",
)
def get_product_by_id(item_id: str):
    """
    Fetches live Walmart product data using the numeric **Item ID**.

    **Example:**  `/api/product/by-id/2187337312`

    The Item ID can be found in the product URL:
    `https://www.walmart.com/ip/Some-Product-Name/**2187337312**`
    """
    if not item_id.isdigit():
        raise HTTPException(status_code=400, detail="item_id must be numeric.")
    url    = _item_id_to_url(item_id)
    result = _scrape_by_url(url)
    return JSONResponse(content=result)


@app.get(
    "/api/product/by-url",
    tags=["Product"],
    summary="Fetch product by full Walmart product URL",
    response_description="Live product data from Walmart",
)
def get_product_by_url(
    url: str = Query(..., description="Full Walmart product URL, e.g. https://www.walmart.com/ip/Product-Name/123456")
):
    """
    Fetches live Walmart product data using the **full product URL**.

    **Example:**
    `/api/product/by-url?url=https://www.walmart.com/ip/Apple-AirPods-Pro/2187337312`
    """
    if not _validate_walmart_url(url):
        raise HTTPException(
            status_code=400,
            detail="URL must be a valid Walmart product URL starting with https://www.walmart.com/ip/",
        )
    result = _scrape_by_url(url)
    return JSONResponse(content=result)


@app.get(
    "/api/product/by-name",
    tags=["Product"],
    summary="Search product by name and fetch first result",
    response_description="Live product data from Walmart (first search result)",
)
def get_product_by_name(
    q: str = Query(..., min_length=2, description="Product search query, e.g. 'Apple AirPods Pro'")
):
    """
    Searches Walmart for the given **product name**, picks the first result,
    then fetches full live data for that product.

    **Example:** `/api/product/by-name?q=Apple+AirPods+Pro`

    > Note: This makes two requests (search + product page), so it may take 2-5s longer.
    """
    item_id = search_item_id(q)
    if not item_id:
        return JSONResponse(
            content=_build_response(
                None,
                f"No results found for query: '{q}'. Try a more specific product name."
            )
        )
    url    = _item_id_to_url(item_id)
    result = _scrape_by_url(url)
    return JSONResponse(content=result)
