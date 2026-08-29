"""Configuration-driven product-listing and product-page parser.

The public fetcher contains no retailer-specific identities.  A private
orchestrator supplies selectors and URL templates for each store at runtime.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..normalize import clean_product_url, empty_item, finalize_item, parse_price_inr

DEFAULT_CARD_SELECTOR = "[data-product-id]"
DEFAULT_ID_ATTRIBUTE = "data-product-id"
DEFAULT_TITLE_SELECTORS = [".name a", ".name", "h3 a", "h4 a", "h1"]
DEFAULT_URL_SELECTORS = [".name a", "h3 a", "h4 a", "a.product-img", "a[href]"]
DEFAULT_IMAGE_SELECTORS = ["img"]
DEFAULT_IMAGE_ATTRIBUTES = ["data-src", "data-original", "data-lazy-src", "src"]
DEFAULT_PRICE_SELECTORS = [".price-new", ".price", "[itemprop='price']"]
DEFAULT_SALE_PRICE_SELECTORS = [".price-new", ".ins"]
DEFAULT_REGULAR_PRICE_SELECTORS = [".price-old", ".del"]
DEFAULT_STOCK_SELECTORS = [".stock", ".product-stock", ".stat-2", ".product-label", "li"]
DEFAULT_MPN_SELECTORS = [".stat-1", ".model", ".sku", "[itemprop='sku']"]


def listing_url(page: int = 1, template: Optional[str] = None, config: Optional[dict] = None) -> str:
    del config
    if not template:
        raise ValueError("listing_url_template is required")
    return template.format(page=int(page))


def _list(config: dict, key: str, default: list[str]) -> list[str]:
    value = config.get(key)
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    return list(default)


def _first(card, selectors: list[str]):
    for selector in selectors:
        element = card.select_one(selector)
        if element:
            return element
    return None


def _text(element) -> Optional[str]:
    if not element:
        return None
    value = element.get_text(" ", strip=True)
    return value or None


def _value(element) -> Optional[str]:
    if not element:
        return None
    for attribute in ("content", "value", "data-value"):
        value = (element.get(attribute) or "").strip()
        if value:
            return value
    return _text(element)


def _id_from_card(card, config: dict) -> Optional[str]:
    attribute = str(config.get("id_attribute") or DEFAULT_ID_ATTRIBUTE).strip()
    if attribute:
        value = (card.get(attribute) or "").strip()
        if value:
            return value
    pattern = str(config.get("id_regex") or "").strip()
    if pattern:
        match = re.search(pattern, str(card), re.I)
        if match:
            return (match.group(1) if match.groups() else match.group(0)).strip() or None
    return None


def _image_from_card(card, page_url: str, config: dict) -> Optional[str]:
    element = _first(card, _list(config, "image_selectors", DEFAULT_IMAGE_SELECTORS))
    if not element:
        return None
    for attribute in _list(config, "image_attributes", DEFAULT_IMAGE_ATTRIBUTES):
        value = (element.get(attribute) or "").strip()
        if value and not value.startswith("data:"):
            return urljoin(page_url, value)
    return None


def _price_from_selectors(card, selectors: list[str]) -> Optional[float]:
    element = _first(card, selectors)
    return parse_price_inr(_value(element)) if element else None


def _prices_from_card(card, config: dict) -> tuple[Optional[float], Optional[float]]:
    sale = _price_from_selectors(
        card, _list(config, "sale_price_selectors", DEFAULT_SALE_PRICE_SELECTORS)
    )
    regular = _price_from_selectors(
        card, _list(config, "regular_price_selectors", DEFAULT_REGULAR_PRICE_SELECTORS)
    )
    if sale is not None and regular is not None:
        return regular, sale
    if sale is not None:
        return sale, None
    if regular is not None:
        return regular, None
    return _price_from_selectors(card, _list(config, "price_selectors", DEFAULT_PRICE_SELECTORS)), None


def _mpn_from_card(card, config: dict) -> Optional[str]:
    element = _first(card, _list(config, "mpn_selectors", DEFAULT_MPN_SELECTORS))
    if not element:
        return None
    value = _text(element)
    pattern = str(config.get("mpn_regex") or "").strip()
    if pattern and value:
        match = re.search(pattern, value, re.I)
        if match:
            value = match.group(1) if match.groups() else match.group(0)
    return value.strip() if value else None


def _availability_from_card(card, config: dict) -> Optional[str]:
    if config.get("listing_implies_in_stock"):
        return "in_stock"
    text = " ".join(
        _text(element) or ""
        for selector in _list(config, "stock_selectors", DEFAULT_STOCK_SELECTORS)
        for element in card.select(selector)
    ).lower()
    if "out of stock" in text or "coming soon" in text or "unavailable" in text:
        return "out_of_stock"
    if "in stock" in text or "available" in text:
        return "in_stock"
    return None


def parse_listing_html(
    html: str, page_url: str, config: Optional[dict] = None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config = config or {}
    soup = BeautifulSoup(html, "lxml")
    card_selector = str(config.get("card_selector") or DEFAULT_CARD_SELECTOR)
    cards = soup.select(card_selector)
    items: list[dict[str, Any]] = []

    for card in cards:
        item = empty_item()
        title_element = _first(card, _list(config, "title_selectors", DEFAULT_TITLE_SELECTORS))
        url_element = _first(card, _list(config, "url_selectors", DEFAULT_URL_SELECTORS))
        href = url_element.get("href") if url_element else None
        regular, sale = _prices_from_card(card, config)
        item["merchant_item_id"] = _id_from_card(card, config)
        item["title"] = _text(title_element)
        item["product_url"] = clean_product_url(urljoin(page_url, href) if href else None)
        item["image_url"] = _image_from_card(card, page_url, config)
        item["mpn"] = _mpn_from_card(card, config)
        item["price"] = regular
        item["sale_price"] = sale
        item["availability"] = _availability_from_card(card, config)
        item["raw_payload"] = {
            "source": "html_listing",
            "page_url": page_url,
            "price_regular": regular,
            "price_sale": sale,
        }
        items.append(finalize_item(item))

    text = soup.get_text(" ", strip=True)
    showing_pattern = str(config.get("showing_regex") or "").strip()
    showing = None
    if showing_pattern:
        match = re.search(showing_pattern, text, re.I)
        if match and len(match.groups()) >= 4:
            showing = {
                "from": int(match.group(1)),
                "to": int(match.group(2)),
                "of": int(match.group(3)),
                "pages": int(match.group(4)),
            }
    return items, {
        "card_selector": card_selector,
        "cards_found": len(cards),
        "showing": showing,
        "health_ok": len(cards) >= int(config.get("min_page1_items") or 10),
    }


def _json_ld_products(soup: BeautifulSoup) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for tag in soup.select('script[type="application/ld+json"]'):
        raw = (tag.string or tag.get_text() or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_type = node.get("@type")
            types = node_type if isinstance(node_type, list) else [node_type]
            if "product" in {str(value).lower() for value in types if value}:
                found.append(node)
            graph = node.get("@graph")
            if isinstance(graph, list):
                for graph_node in graph:
                    if not isinstance(graph_node, dict):
                        continue
                    graph_type = graph_node.get("@type")
                    graph_types = graph_type if isinstance(graph_type, list) else [graph_type]
                    if "product" in {str(value).lower() for value in graph_types if value}:
                        found.append(graph_node)
    return found


def _brand_from_ld(node: dict[str, Any]) -> Optional[str]:
    value = node.get("brand")
    if isinstance(value, dict):
        value = value.get("name")
    return str(value).strip() if value and str(value).strip() else None


def _soft_deleted(
    requested_url: str, final_url: str, soup: BeautifulSoup, config: dict
) -> bool:
    final = urlparse(final_url)
    requested = urlparse(requested_url)
    homepage_paths = set(_list(config, "homepage_paths", ["/", "/index.php"]))
    final_path = (final.path or "/").rstrip("/") or "/"
    if final_path not in homepage_paths:
        return False
    requested_path = requested.path or ""
    looked_like_product = requested_path not in ("", "/", "/index.php") or bool(requested.query)
    if not looked_like_product:
        return False
    product_markers = _list(
        config,
        "product_markers",
        ["[itemtype*='Product']", "#product", ".product-info", ".product-details"],
    )
    return not any(soup.select_one(selector) for selector in product_markers)


def parse_pdp_html(
    html: str,
    *,
    requested_url: str,
    final_url: Optional[str] = None,
    config: Optional[dict] = None,
) -> dict[str, Any]:
    config = config or {}
    final = (final_url or requested_url or "").strip()
    soup = BeautifulSoup(html, "lxml")
    item = empty_item()
    item["product_url"] = clean_product_url(final or requested_url)
    raw: dict[str, Any] = {
        "source": "html_pdp",
        "requested_url": requested_url,
        "final_url": final,
    }

    if _soft_deleted(requested_url, final, soup, config):
        raw.update({"soft_deleted": True, "gone": True})
        item["availability"] = "out_of_stock"
        item["raw_payload"] = raw
        return finalize_item(item)

    products = _json_ld_products(soup)
    if not products and not any(
        soup.select_one(selector)
        for selector in _list(
            config,
            "product_markers",
            ["[itemtype*='Product']", "#product", ".product-info", ".product-details"],
        )
    ):
        raw.update({"soft_deleted": True, "gone": True})
        item["availability"] = "out_of_stock"
        item["raw_payload"] = raw
        return finalize_item(item)

    if products:
        node = products[0]
        item["title"] = str(node.get("name")).strip() if node.get("name") else None
        item["brand"] = _brand_from_ld(node)
        model = node.get("model")
        mpn = node.get("mpn") or model or node.get("sku")
        item["mpn"] = str(mpn).strip() if mpn else None
        raw["json_ld_sku"] = node.get("sku")
        raw["json_ld_model"] = model
        offers = node.get("offers")
        offer = offers[0] if isinstance(offers, list) and offers else offers
        if isinstance(offer, dict):
            item["price"] = parse_price_inr(str(offer.get("price") or ""))
            availability = str(offer.get("availability") or "").lower()
            if "outofstock" in availability or "out_of_stock" in availability:
                item["availability"] = "out_of_stock"
            elif "instock" in availability or "in_stock" in availability:
                item["availability"] = "in_stock"

    page_text = soup.get_text("\n", strip=True)
    for field, config_key in (("mpn", "mpn_regex"), ("brand", "brand_regex")):
        if item.get(field):
            continue
        pattern = str(config.get(config_key) or "").strip()
        if pattern:
            match = re.search(pattern, page_text, re.I)
            if match:
                value = (match.group(1) if match.groups() else match.group(0)).strip()
                if value:
                    item[field] = value
                    raw[f"{field}_text"] = value
    if not item.get("title"):
        title = soup.select_one("h1, title")
        item["title"] = _text(title)
    if not item.get("availability"):
        item["availability"] = "out_of_stock" if "out of stock" in page_text.lower() else "in_stock"
    raw["soft_deleted"] = False
    item["raw_payload"] = raw
    return finalize_item(item)
