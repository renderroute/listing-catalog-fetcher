"""Shared normalize helpers for listing HTML catalogs."""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


PRICE_RE = re.compile(r"([0-9][0-9,]*\.?[0-9]*)")


def parse_price_inr(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    cleaned = str(text).replace("₹", "").replace("Rs.", "").replace("Rs", "")
    m = PRICE_RE.search(cleaned)
    if not m:
        return None
    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return value if value != 0 else None


def clean_product_url(url: Optional[str]) -> Optional[str]:
    """Drop listing search junk (?search=&page=&limit=) from product links."""
    if not url:
        return None
    url = str(url).strip()
    if not url:
        return None
    parsed = urlparse(url)
    drop = {"search", "page", "limit", "sort", "order"}
    kept = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k.lower() not in drop]
    query = urlencode(kept)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, ""))


def empty_item() -> dict[str, Any]:
    return {
        "merchant_item_id": None,
        "product_url": None,
        "image_url": None,
        "title": None,
        "product_type": None,
        "brand": None,
        "mpn": None,
        "gtin": None,
        "ean": None,
        "upc": None,
        "feed_condition": "new",
        "availability": None,
        "price": None,
        "sale_price": None,
        "effective_price": None,
        "raw_payload": {},
    }


def finalize_item(item: dict[str, Any]) -> dict[str, Any]:
    """Fill effective_price and normalize availability.

    OpenCart-style cards map current price to sale/new and MRP to regular/old.
    When sale/new is not lower than regular/old (inverted or broken markup),
    prefer sale/new as the current price and drop the fake discount. This was
    seen on Vedant cards where price-old was struck through but lower than
    price-new (e.g. ₹139,675 struck, ₹168,000 current).
    """
    price = item.get("price")
    sale = item.get("sale_price")
    if sale is not None and price is not None and sale < price:
        item["effective_price"] = sale
    elif sale is not None and price is not None and sale >= price:
        item["effective_price"] = sale
        item["price"] = sale
        item["sale_price"] = None
        raw = item.get("raw_payload")
        if isinstance(raw, dict):
            raw["price_inverted_markup"] = True
            raw["price_regular_raw"] = price
            raw["price_sale_raw"] = sale
    elif sale is not None and price is None:
        item["effective_price"] = sale
        item["price"] = sale
        item["sale_price"] = None
    else:
        item["effective_price"] = price

    avail = (item.get("availability") or "").strip().lower().replace(" ", "_").replace("-", "_")
    if avail in ("in_stock", "instock", "available"):
        item["availability"] = "in_stock"
    elif avail in ("out_of_stock", "outofstock", "oos", "unavailable"):
        item["availability"] = "out_of_stock"
    return item


def item_is_usable(item: dict[str, Any]) -> bool:
    return bool(item.get("merchant_item_id") and item.get("title") and item.get("product_url"))
