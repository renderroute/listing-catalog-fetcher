"""Lean listing-catalog JSON schema (generic listing HTML envelope)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "pcpmf_listing_catalog_v1"
USER_AGENT = "ListingCatalogFetcher/0.1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_envelope(
    *,
    retailer_key: str,
    feed_format: str,
    items: list[dict[str, Any]],
    fetched_at: str | None = None,
    stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "retailer_key": retailer_key,
        "feed_format": feed_format,
        "fetched_at": fetched_at or utc_now_iso(),
        "item_count": len(items),
        "items": items,
    }
    if stats:
        envelope["stats"] = stats
    return envelope


def money(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
