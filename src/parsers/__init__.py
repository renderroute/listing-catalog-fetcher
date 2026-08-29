"""Parser registry for generic listing HTML platforms."""

from __future__ import annotations

from types import ModuleType
from typing import Optional

from . import html_listing

PARSERS: dict[str, ModuleType] = {
    "html_listing": html_listing,
    "opencart_listing": html_listing,
}


def resolve_parser(store: dict) -> ModuleType:
    """
    Resolve the generic parser by explicit parser key.

    Store-specific selectors are configuration in the private dispatch payload,
    not code in this public repository.
    """
    platform = str(store.get("platform") or "listing_html").strip().lower()
    key = str(store.get("parser") or store.get("parser_key") or "").strip().lower()
    if not key and platform in PARSERS:
        key = platform
    if not key and platform in ("listing_html", "html_listing"):
        key = "html_listing"
    if key in PARSERS:
        return PARSERS[key]
    raise KeyError(f"No listing parser for key={key!r} (known: {', '.join(sorted(PARSERS))})")


def get_parser(key: str) -> Optional[ModuleType]:
    return PARSERS.get((key or "").strip().lower())
