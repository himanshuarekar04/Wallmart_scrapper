"""
parser.py
---------
Transforms the raw __NEXT_DATA__ JSON blob from a Walmart product page
into the structured response format expected by the API.

Data path (may vary slightly with Walmart deployments):
  data["props"]["pageProps"]["initialData"]["data"]["product"]
  data["props"]["pageProps"]["initialData"]["data"]["idml"]   ← spec / description
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

WALMART_BASE = "https://www.walmart.com"
IMAGE_BASE   = "https://i5.walmartimages.com/asr"


# ---------------------------------------------------------------------------
# Safe getters
# ---------------------------------------------------------------------------

def _safe(obj: Any, *keys, default=None):
    """Safely traverse nested dicts/lists without raising KeyError/TypeError."""
    for key in keys:
        try:
            if isinstance(obj, dict):
                obj = obj[key]
            elif isinstance(obj, list):
                obj = obj[int(key)]
            else:
                return default
        except (KeyError, IndexError, TypeError, ValueError):
            return default
    return obj if obj is not None else default


def _price_float(val: Any) -> Optional[float]:
    """Convert a price value to float, handling None and non-numeric types."""
    try:
        return round(float(val), 2)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def _resolve_image(image_info: Any) -> Optional[str]:
    """Extract a full image URL from Walmart image objects (various shapes)."""
    if not image_info:
        return None
    if isinstance(image_info, str):
        if image_info.startswith("http"):
            return image_info
        return f"{IMAGE_BASE}/{image_info}"
    if isinstance(image_info, dict):
        return (
            image_info.get("url")
            or image_info.get("src")
            or image_info.get("imageUrl")
        )
    return None


def _extract_images(product: dict) -> list[str]:
    """Collect all image URLs for the product."""
    images = []

    # imageInfo > allImages
    all_imgs = _safe(product, "imageInfo", "allImages", default=[])
    for img in all_imgs:
        url = _resolve_image(img)
        if url:
            images.append(url)

    # fallback: single thumbnailUrl / imageUrl
    if not images:
        thumb = _safe(product, "imageInfo", "thumbnailUrl")
        if thumb:
            images.append(_resolve_image(thumb) or thumb)

    return images


# ---------------------------------------------------------------------------
# Price extraction
# ---------------------------------------------------------------------------

def _extract_price(product: dict) -> dict:
    price_info = _safe(product, "priceInfo", default={})

    current_price   = _price_float(_safe(price_info, "currentPrice", "price"))
    was_price       = _price_float(_safe(price_info, "wasPrice",     "price"))
    unit_price      = _price_float(_safe(price_info, "unitPrice",    "price"))
    unit_price_disp = _safe(price_info, "unitPrice", "priceDisplay")
    currency        = _safe(price_info, "currentPrice", "currencyUnit", default="USD")

    # Show-discount percentage
    show_discount = 0
    if current_price and was_price and was_price > current_price:
        show_discount = round(((was_price - current_price) / was_price) * 100)

    price_display = f"${current_price}" if current_price else None

    return {
        "current_price":      current_price,
        "was_price":          was_price,
        "unit_price":         unit_price,
        "unit_price_display": unit_price_disp,
        "price_display":      price_display,
        "currency":           currency,
        "show_discount":      show_discount,
    }


# ---------------------------------------------------------------------------
# Availability extraction
# ---------------------------------------------------------------------------

def _extract_availability(product: dict) -> dict:
    avail_status = _safe(product, "availabilityStatus", default="UNKNOWN")
    in_stock     = avail_status in ("IN_STOCK", "AVAILABLE")

    # Fulfillment options
    fulfillment  = _safe(product, "fulfillmentOptions", default=[])
    ship_avail   = any(f.get("type") == "SHIPPING" for f in fulfillment if isinstance(f, dict))
    pickup_avail = any(f.get("type") == "PICKUP"   for f in fulfillment if isinstance(f, dict))
    deliv_avail  = any(f.get("type") == "DELIVERY" for f in fulfillment if isinstance(f, dict))

    return {
        "status":   avail_status,
        "in_stock": in_stock,
        "fulfillment": {
            "shipping": ship_avail,
            "pickup":   pickup_avail,
            "delivery": deliv_avail,
        },
    }


# ---------------------------------------------------------------------------
# Ratings extraction
# ---------------------------------------------------------------------------

def _extract_ratings(product: dict) -> dict:
    reviews = _safe(product, "reviews", default={})
    total_reviews  = _safe(reviews, "totalReviewCount",  default=0)
    avg_rating     = _safe(reviews, "averageOverallRating", default=None)
    if avg_rating is None:
        avg_rating = _safe(product, "averageRating", default=None)
    if avg_rating:
        try:
            avg_rating = round(float(avg_rating), 2)
        except (TypeError, ValueError):
            avg_rating = None

    # Rating histogram {1: n, 2: n, 3: n, 4: n, 5: n}
    hist_raw  = _safe(reviews, "ratingValueOneCount"), \
                _safe(reviews, "ratingValueTwoCount"), \
                _safe(reviews, "ratingValueThreeCount"), \
                _safe(reviews, "ratingValueFourCount"), \
                _safe(reviews, "ratingValueFiveCount")
    histogram = {str(i + 1): (v or 0) for i, v in enumerate(hist_raw)}

    return {
        "rating_star":    avg_rating,
        "total_reviews":  total_reviews,
        "histogram":      histogram,
    }


# ---------------------------------------------------------------------------
# Variants (models) extraction
# ---------------------------------------------------------------------------

def _extract_variants(product: dict) -> list[dict]:
    """
    Walmart stores variants inside product["variantList"] or product["variants"].
    Each variant contains its own price / availability / images.
    """
    raw_variants = _safe(product, "variantList", default=None)
    if not raw_variants:
        raw_variants = _safe(product, "variants", default=[])

    models = []
    for v in (raw_variants or []):
        if not isinstance(v, dict):
            continue

        variant_id    = v.get("variantId") or v.get("id")
        name_parts    = []
        for attr in (v.get("variantAttributes") or []):
            val = attr.get("value") if isinstance(attr, dict) else None
            if val:
                name_parts.append(val)
        name = ", ".join(name_parts) if name_parts else v.get("name", "")

        v_price_info  = v.get("priceInfo") or {}
        v_current_p   = _price_float(_safe(v_price_info, "currentPrice", "price")
                                     or _safe(v, "priceInfo", "currentPrice", "price"))
        v_was_p       = _price_float(_safe(v_price_info, "wasPrice", "price"))
        in_stock      = v.get("availabilityStatus", "") in ("IN_STOCK", "AVAILABLE")

        # Images specific to this variant
        v_images = []
        for img in (v.get("images") or []):
            u = _resolve_image(img)
            if u:
                v_images.append(u)
        if not v_images and v.get("imageUrl"):
            v_images.append(_resolve_image(v["imageUrl"]) or v["imageUrl"])

        models.append({
            "variant_id":           str(variant_id) if variant_id else None,
            "name":                 name,
            "price":                v_current_p,
            "price_before_discount":v_was_p,
            "in_stock":             in_stock,
            "stock_status":         v.get("availabilityStatus", "UNKNOWN"),
            "images":               v_images,
        })

    return models


# ---------------------------------------------------------------------------
# Attributes / Specifications extraction
# ---------------------------------------------------------------------------

def _extract_attributes(product: dict, idml: dict) -> list[dict]:
    """
    Merge product-level specifications with IDML detailed attributes.
    """
    attrs = []

    # From product.specifications (list of {name, value})
    for spec in (_safe(product, "specifications", default=[]) or []):
        if not isinstance(spec, dict):
            continue
        name  = spec.get("name") or spec.get("key")
        value = spec.get("value")
        if name and value:
            attrs.append({"name": name, "value": str(value)})

    # From idml.modules (nested section → attributes list)
    if isinstance(idml, dict):
        for module in (idml.get("modules") or []):
            if not isinstance(module, dict):
                continue
            for attr in (module.get("attributes") or []):
                if not isinstance(attr, dict):
                    continue
                name  = attr.get("name") or attr.get("displayName")
                value = attr.get("value") or attr.get("displayValue")
                if name and value:
                    attrs.append({"name": str(name), "value": str(value)})

    return attrs


# ---------------------------------------------------------------------------
# Categories extraction
# ---------------------------------------------------------------------------

def _extract_categories(product: dict) -> list[dict]:
    cats = []
    for cat in (_safe(product, "breadCrumb", default=[]) or []):
        if not isinstance(cat, dict):
            continue
        cats.append({
            "catid":        cat.get("id") or cat.get("catId"),
            "display_name": cat.get("name") or cat.get("displayName"),
            "url":          cat.get("url"),
        })
    return cats


# ---------------------------------------------------------------------------
# Seller extraction
# ---------------------------------------------------------------------------

def _extract_seller(product: dict) -> dict:
    seller_info = _safe(product, "sellerInfo", default={}) or {}
    offers      = _safe(product, "offers", default=[]) or []
    first_offer = offers[0] if offers else {}

    seller_id   = (seller_info.get("sellerId")
                   or first_offer.get("sellerId")
                   or _safe(product, "sellerId"))
    seller_name = (seller_info.get("sellerDisplayName")
                   or seller_info.get("sellerName")
                   or first_offer.get("sellerName")
                   or "Walmart")
    shop_type   = "walmart" if str(seller_id) in ("0", "") else "third_party"

    return {
        "shop_id":   str(seller_id) if seller_id else None,
        "shop_name": seller_name,
        "shop_type": shop_type,
    }


# ---------------------------------------------------------------------------
# Master parser
# ---------------------------------------------------------------------------

def parse_product(next_data: dict) -> Optional[dict]:
    """
    Extract and normalise all product fields from the __NEXT_DATA__ dict.
    Returns the final structured payload, or None on failure.
    """
    try:
        initial_data = _safe(next_data, "props", "pageProps", "initialData", "data", default={})
        product      = _safe(initial_data, "product",  default={})
        idml         = _safe(initial_data, "idml",     default={})

        if not product:
            logger.error("Product key missing in __NEXT_DATA__")
            return None

        # ---- Core fields ----
        item_id   = str(_safe(product, "usItemId") or _safe(product, "itemId") or "")
        upc       = _safe(product, "upc")
        gtin      = _safe(product, "gtin")
        title     = _safe(product, "name", default="")
        brand     = _safe(product, "brand")
        short_desc= _safe(product, "shortDescription") or _safe(idml, "shortDescription")
        long_desc = _safe(product, "longDescription")  or _safe(idml, "longDescription")
        condition = _safe(product, "condition")
        is_adult  = bool(_safe(product, "isAdultProduct", default=False))
        ctime     = _safe(product, "publishedDate")      # may be epoch or ISO string

        # Build product URL
        seo_url   = _safe(product, "canonicalUrl") or _safe(product, "seoUrl")
        if seo_url and not seo_url.startswith("http"):
            seo_url = f"https://www.walmart.com{seo_url}"
        if not seo_url and item_id:
            seo_url = f"https://www.walmart.com/ip/product/{item_id}"

        # ---- Sub-sections ----
        images      = _extract_images(product)
        price_info  = _extract_price(product)
        availability= _extract_availability(product)
        rating_info = _extract_ratings(product)
        variants    = _extract_variants(product)
        attributes  = _extract_attributes(product, idml)
        categories  = _extract_categories(product)
        seller      = _extract_seller(product)

        # Determine item_status
        avail_status = availability["status"]
        item_status  = "normal" if availability["in_stock"] else "out_of_stock"

        # ---- Assemble final payload ----
        item = {
            # Identification
            "item_id":          item_id,
            "upc":              upc,
            "gtin":             gtin,
            "item_status":      item_status,
            "status":           1 if availability["in_stock"] else 0,
            "item_type":        0,
            "reference_item_id":"",

            # Content
            "title":            title,
            "brand":            brand,
            "brand_id":         None,
            "image":            images[0] if images else None,
            "images":           images,
            "description":      long_desc,
            "short_description":short_desc,

            # Flags
            "is_adult":         is_adult,
            "is_preview":       False,
            "condition":        condition,
            "currency":         price_info["currency"],
            "ctime":            ctime,
            "url":              seo_url,

            # Pricing
            "price":            price_info,
            "show_discount":    price_info["show_discount"],

            # Availability
            "availability":     availability,

            # Ratings
            "item_rating":      rating_info,

            # Seller / Shop
            "shop_id":          seller["shop_id"],
            "shop_name":        seller["shop_name"],
            "shop_type":        seller["shop_type"],

            # Variants (models)
            "models":           variants,

            # Specs & Categories
            "attributes":       attributes,
            "categories":       categories,
        }

        return item

    except Exception as exc:
        logger.exception(f"Unexpected error in parse_product: {exc}")
        return None
