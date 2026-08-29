"""CLI: fetch listing HTML catalogs into lean JSON envelopes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import build_envelope
from .http_fetch import fetch_html, polite_delay
from .normalize import item_is_usable
from .parsers import resolve_parser

ROOT = Path(__file__).resolve().parents[1]


def log(msg: str, *, error: bool = False) -> None:
    print(msg, file=sys.stderr if error else sys.stdout, flush=True)


def _num(value: Any, fallback: Any) -> Any:
    if value is None or value == "":
        return fallback
    return value


def _int(value: Any, fallback: int) -> int:
    try:
        return int(_num(value, fallback))
    except (TypeError, ValueError):
        return fallback


def stores_from_inline(args: argparse.Namespace) -> list[dict]:
    key = (args.inline_store or "").strip()
    template = (args.listing_url_template or "").strip()
    if not key or not template:
        return []
    return [
        {
            "key": key,
            "platform": "listing_html",
            "listing_url_template": template,
            "page_size_hint": int(args.page_size or 20),
            "min_page1_items": 10,
            "enrich_limit": int(args.enrich_limit or 0),
            "enabled": True,
        }
    ]


def stores_from_json(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and isinstance(raw.get("stores"), list):
        raw = raw["stores"]
    if not isinstance(raw, list):
        raise ValueError("stores JSON must be a list or {stores: [...]}")
    out: list[dict] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or row.get("retailer_key") or "").strip()
        template = str(row.get("listing_url_template") or row.get("feed_url") or "").strip()
        if not key or not template:
            continue
        row_out = dict(row)
        row_out["key"] = key
        row_out["listing_url_template"] = template
        row_out["platform"] = str(row.get("platform") or "listing_html").strip() or "listing_html"
        row_out["enabled"] = bool(row.get("enabled", True))
        out.append(row_out)
    return out


def _failure_row(key: str, exc: Exception | None = None, error: str = "") -> dict:
    err = (error or (str(exc) if exc else "")).strip() or "Listing fetch failed"
    return {
        "key": key,
        "retailer_key": key,
        "error": err,
        "http_status": 403 if "403" in err else 0,
        "final": True,
    }


def _write_status(out_dir: Path, *, ok: int, failed: int, failed_keys: list, failed_rows: list) -> None:
    status_path = out_dir / "_fetch_status.json"
    status_path.write_text(
        json.dumps(
            {
                "ok": ok,
                "failed": failed,
                "failed_keys": failed_keys,
                "failures": failed_rows,
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    fail_path = out_dir / "_failures.json"
    fail_path.write_text(
        json.dumps({"failures": failed_rows, "final": True}, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_bridge_keys(out_dir: Path, keys: list[str]) -> None:
    (out_dir / "_bridge_keys.txt").write_text(",".join(keys), encoding="utf-8")


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        mid = str(item.get("merchant_item_id") or "").strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        out.append(item)
    return out


def fetch_store_listings(store: dict) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    parser = resolve_parser(store)
    key = str(store.get("key") or "").strip()
    template = str(store.get("listing_url_template") or "").strip()
    page_size = _int(store.get("page_size_hint") or store.get("page_size"), 20)
    min_page1 = _int(store.get("min_page1_items"), 10)
    max_pages = store.get("max_pages")
    max_pages_i = _int(max_pages, 0) if max_pages not in (None, "") else 0
    enrich_limit = _int(store.get("enrich_limit"), 0)
    enrich_mode = str(store.get("enrich_mode") or "").strip().lower()
    known_item_ids = {
        str(value).strip()
        for value in (store.get("known_item_ids") or [])
        if str(value).strip()
    }
    enrich_item_ids = {
        str(value).strip()
        for value in (store.get("enrich_item_ids") or [])
        if str(value).strip()
    }
    delay_min = float(_num(store.get("delay_seconds_min"), 1.5) or 1.5)
    delay_max = float(_num(store.get("delay_seconds_max"), 3.5) or 3.5)

    all_items: list[dict[str, Any]] = []
    page_metas: list[dict[str, Any]] = []
    page = 1
    while True:
        if max_pages_i and page > max_pages_i:
            break
        url = parser.listing_url(page, template=template, config=store)
        log(f"  page {page}: {url}")
        status, final_url, html = fetch_html(url, delay_min=delay_min, delay_max=delay_max)
        if status != 200:
            raise RuntimeError(f"HTTP {status} for {url} (final {final_url})")
        if len(html) < 2000:
            raise RuntimeError(f"Response too small ({len(html)} chars) — possible block page for {url}")

        items, meta = parser.parse_listing_html(html, url, config=store)
        usable = [i for i in items if item_is_usable(i)]
        page_metas.append(
            {
                "page": page,
                "url": url,
                "final_url": final_url,
                "cards_found": meta.get("cards_found"),
                "usable": len(usable),
                "showing": meta.get("showing"),
                "health_ok": meta.get("health_ok"),
            }
        )

        if page == 1:
            if len(usable) < min_page1:
                raise RuntimeError(
                    f"Page 1 health fail: usable={len(usable)} < min_page1_items={min_page1}"
                )

        if not usable:
            log(f"  page {page}: empty — stop")
            break

        all_items.extend(usable)

        # Short page → last page
        if len(usable) < page_size:
            log(f"  page {page}: short ({len(usable)} < {page_size}) — stop")
            break

        showing = meta.get("showing") or {}
        total_pages = showing.get("pages")
        if total_pages and page >= int(total_pages):
            log(f"  page {page}: reached showing.pages={total_pages} — stop")
            break

        page += 1

    items = _dedupe_items(all_items)
    stats: dict[str, Any] = {
        "listing_pages": len(page_metas),
        "items_before_dedupe": len(all_items),
        "items_total": len(items),
        "page_metas": page_metas,
        "enriched": 0,
        "enrich_candidates": 0,
        "new_items": 0,
        "missing_checked": 0,
        "marked_gone": 0,
    }

    # The private orchestrator supplies known IDs and one-time incomplete-item
    # targets. New listing IDs are also enriched once. A plain public/manual
    # run remains listing-only unless it explicitly supplies enrich_limit.
    if enrich_mode == "targeted":
        need = [
            i for i in items
            if i.get("product_url")
            and (
                str(i.get("merchant_item_id") or "").strip() not in known_item_ids
                or str(i.get("merchant_item_id") or "").strip() in enrich_item_ids
            )
        ]
        stats["new_items"] = sum(
            1 for i in items
            if str(i.get("merchant_item_id") or "").strip() not in known_item_ids
        )
    elif enrich_limit > 0:
        # Backward-compatible controlled test mode for an inline/manual run.
        need = [i for i in items if not i.get("mpn") and i.get("product_url")]
    else:
        need = []

    stats["enrich_candidates"] = len(need)
    if need:
        enriched = 0
        for item in need:
            if enrich_limit > 0 and enriched >= enrich_limit:
                break
            url = str(item.get("product_url") or "").strip()
            if not url:
                continue
            if not isinstance(item.get("raw_payload"), dict):
                item["raw_payload"] = {}
            item["raw_payload"]["listing_pdp_checked"] = True
            enriched += 1
            try:
                status, final_url, html = fetch_html(url, delay_min=delay_min, delay_max=delay_max)
                if status != 200:
                    log(f"  enrich skip HTTP {status} {url}", error=True)
                    continue
                pdp = parser.parse_pdp_html(
                    html, requested_url=url, final_url=final_url, config=store
                )
                item["raw_payload"]["pdp"] = pdp.get("raw_payload") or {}
                if pdp.get("raw_payload", {}).get("soft_deleted"):
                    item["availability"] = "out_of_stock"
                    item.setdefault("raw_payload", {})["enrich_gone"] = True
                else:
                    for field in ("mpn", "brand", "title", "gtin", "ean", "upc"):
                        if pdp.get(field) and not item.get(field):
                            item[field] = pdp[field]
                    if pdp.get("price") is not None and item.get("price") is None:
                        item["price"] = pdp["price"]
                        from .normalize import finalize_item

                        finalize_item(item)
            except Exception as exc:
                log(f"  enrich error {url}: {exc}", error=True)
        stats["enriched"] = enriched

    # Confirm missing items (soft-delete / OOS)
    confirm = store.get("missing_targets") or store.get("confirm_missing") or []
    if isinstance(confirm, list) and confirm:
        gone = 0
        checked = 0
        by_id = {str(i.get("merchant_item_id")): i for i in items}
        for row in confirm:
            if not isinstance(row, dict):
                continue
            mid = str(row.get("merchant_item_id") or "").strip()
            url = str(row.get("product_url") or "").strip()
            if not url:
                continue
            # Skip if still present on listing
            if mid and mid in by_id:
                continue
            try:
                status, final_url, html = fetch_html(url, delay_min=delay_min, delay_max=delay_max)
                checked += 1
                pdp = parser.parse_pdp_html(
                    html, requested_url=url, final_url=final_url, config=store
                )
                if not isinstance(pdp.get("raw_payload"), dict):
                    pdp["raw_payload"] = {}
                pdp["raw_payload"]["listing_missing_pdp_checked"] = True
                if status == 404 or pdp.get("raw_payload", {}).get("soft_deleted") or pdp.get("availability") == "out_of_stock":
                    gone += 1
                    stub = pdp if pdp.get("merchant_item_id") else dict(pdp)
                    if mid and not stub.get("merchant_item_id"):
                        stub["merchant_item_id"] = mid
                    stub["availability"] = "out_of_stock"
                    stub.setdefault("raw_payload", {})["missing_confirm"] = True
                    items.append(stub)
            except Exception as exc:
                log(f"  confirm_missing error {url}: {exc}", error=True)
        stats["missing_checked"] = checked
        stats["marked_gone"] = gone

    log(f"  {key}: items={len(items)} pages={stats['listing_pages']} enriched={stats['enriched']}")
    return items, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch public listing HTML catalogs")
    parser.add_argument("--out-dir", default=str(ROOT / ".out"))
    parser.add_argument("--stores-json", default="", help="Dynamic store list JSON file")
    parser.add_argument("--inline-store", default="", help="Single retailer key")
    parser.add_argument("--listing-url-template", default="", help="URL template with {page}")
    parser.add_argument("--page-size", type=int, default=20, help="Expected items per page")
    parser.add_argument("--enrich-limit", type=int, default=0, help="Max PDP enrich calls (default 0)")
    parser.add_argument("--dry-run", action="store_true", help="Fetch but do not write files")
    args = parser.parse_args(argv)

    inline = stores_from_inline(args)
    if inline:
        stores = inline
        if args.enrich_limit:
            stores[0]["enrich_limit"] = int(args.enrich_limit)
        log("mode=inline dynamic store")
    elif (args.stores_json or "").strip():
        stores = stores_from_json(Path(args.stores_json))
        log(f"mode=stores-json count={len(stores)}")
    else:
        log("Provide --stores-json or --inline-store + --listing-url-template", error=True)
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ok = 0
    failed = 0
    failed_keys: list[str] = []
    failed_rows: list[dict] = []
    bridge_keys: list[str] = []

    for store in stores:
        key = str(store.get("key") or "").strip()
        if not key:
            continue
        if not store.get("enabled", True):
            log(f"skip {key} (disabled)")
            continue
        log(f"fetch {key} ...")
        try:
            items, stats = fetch_store_listings(store)
            envelope = build_envelope(
                retailer_key=key,
                feed_format="listing_html",
                items=items,
                stats=stats,
            )
            if not args.dry_run:
                path = out_dir / f"{key}.json"
                path.write_text(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                log(f"  wrote {path}")
            ok += 1
            bridge_keys.append(key)
        except Exception as exc:
            failed += 1
            failed_keys.append(key)
            failed_rows.append(_failure_row(key, exc))
            log(f"  FAIL {key}: {exc}", error=True)

    if not args.dry_run:
        _write_bridge_keys(out_dir, bridge_keys)
        _write_status(
            out_dir,
            ok=ok,
            failed=failed,
            failed_keys=failed_keys,
            failed_rows=failed_rows,
        )

    log(f"done ok={ok} failed={failed}")
    if failed and ok == 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
