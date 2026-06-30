# Walmart U.S. Live Product Scraper — POC

A lightweight FastAPI backend that fetches **real-time product data** from Walmart U.S. (`walmart.com`) using `curl_cffi` Chrome TLS impersonation. No proxy required (POC stage). No storage — all data is fetched live on each request.

---

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Start the server
```bash
python run.py
```

Server starts at: `http://127.0.0.1:8000`

### 3. Test via Postman
Import `walmart_scraper_poc.postman_collection.json` into Postman.

---

## API Endpoints

Base URL: `http://127.0.0.1:8000`

### `GET /health`
Liveness check.
```json
{"status": "ok", "service": "walmart-scraper-poc"}
```

---

### `GET /api/product/by-id/{item_id}`
Fetch live product data by **Walmart Item ID** (numeric).

**Example:**
```
GET http://127.0.0.1:8000/api/product/by-id/2187337312
```

> Item IDs appear at the end of product URLs:
> `https://www.walmart.com/ip/Product-Name/**2187337312**`

---

### `GET /api/product/by-url?url=...`
Fetch live product data by **full Walmart product URL**.

**Example:**
```
GET http://127.0.0.1:8000/api/product/by-url?url=https://www.walmart.com/ip/Apple-AirPods-Pro/2187337312
```

---

### `GET /api/product/by-name?q=...`
**Search** Walmart by product name → fetch first result.

**Example:**
```
GET http://127.0.0.1:8000/api/product/by-name?q=Apple+AirPods+Pro
```

> ⚠️ Makes 2 requests internally (search + product page). Expect ~5–10s response time.

---

## Response Format

All endpoints return the same envelope:

```json
{
  "bff_meta": null,
  "error": null,
  "error_msg": null,
  "data": {
    "item": {
      "item_id": "2187337312",
      "upc": "...",
      "gtin": "...",
      "item_status": "normal",
      "status": 1,
      "title": "Apple AirPods Pro (2nd Generation)",
      "brand": "Apple",
      "image": "https://i5.walmartimages.com/...",
      "images": ["url1", "url2", "..."],
      "description": "...",
      "short_description": "...",
      "currency": "USD",
      "show_discount": 20,
      "price": {
        "current_price": 189.99,
        "was_price": 249.00,
        "unit_price": null,
        "unit_price_display": null,
        "price_display": "$189.99",
        "currency": "USD",
        "show_discount": 20
      },
      "availability": {
        "status": "IN_STOCK",
        "in_stock": true,
        "fulfillment": {
          "shipping": true,
          "pickup": true,
          "delivery": false
        }
      },
      "item_rating": {
        "rating_star": 4.7,
        "total_reviews": 12450,
        "histogram": {"1": 120, "2": 80, "3": 200, "4": 900, "5": 11150}
      },
      "shop_id": "0",
      "shop_name": "Walmart",
      "shop_type": "walmart",
      "models": [
        {
          "variant_id": "...",
          "name": "White",
          "price": 189.99,
          "price_before_discount": 249.00,
          "in_stock": true,
          "stock_status": "IN_STOCK",
          "images": ["url1"]
        }
      ],
      "attributes": [
        {"name": "Brand", "value": "Apple"},
        {"name": "Color", "value": "White"}
      ],
      "categories": [
        {"catid": "...", "display_name": "Electronics", "url": "/..."},
        {"catid": "...", "display_name": "Headphones", "url": "/..."}
      ],
      "url": "https://www.walmart.com/ip/Apple-AirPods-Pro/2187337312"
    }
  }
}
```

### Error Response
```json
{
  "bff_meta": null,
  "error": "SCRAPER_ERROR",
  "error_msg": "Failed to fetch the product page. Walmart may have blocked the request.",
  "data": null
}
```

---

## Project Structure

```
Walmart_scraper/
├── main.py          ← FastAPI app (routes & response envelope)
├── scraper.py       ← HTTP fetcher (curl_cffi Chrome impersonation)
├── parser.py        ← __NEXT_DATA__ JSON → structured output
├── search.py        ← Walmart search → first result item ID
├── run.py           ← One-click launcher
├── requirements.txt
├── .env
└── walmart_scraper_poc.postman_collection.json
```

---

## Interactive API Docs

FastAPI auto-generates Swagger UI and ReDoc:
- **Swagger UI:** http://127.0.0.1:8000/docs
- **ReDoc:**      http://127.0.0.1:8000/redoc

---

## Notes for POC Stage

- **No proxy** — running on local IP. May be rate-limited by Walmart after ~20–30 requests/hour.
- **Default US location** — no ZIP code or store ID needed.
- **No storage** — every request fetches fresh live data.
- **curl_cffi only** — lightweight, no Playwright/browser needed.

Future additions (post-POC):
- Proxy / rotating proxy support
- ZIP code-aware pricing
- Caching layer (Redis)
- Batch product fetching
