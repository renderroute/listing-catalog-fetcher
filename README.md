# listing-catalog-fetcher

Generic scheduled / dispatched fetcher for **public store listing HTML**
(configurable product grids and product detail pages).

This repository is intentionally **anonymous**. It does not document, name, or
call any downstream application ingest endpoint. Store URLs and selectors
arrive only in the runtime dispatch payload from a private orchestrator.

## What it does

1. Accepts a **dynamic** store list via:
   - `workflow_dispatch` inputs: `store` + `listing_url_template` + `page_size`
   - `repository_dispatch` type `fetch-listings` with `client_payload.stores`
   - or a JSON file passed as `--stores-json`
2. Fetches selected retailer listings concurrently, with polite per-store delays and retries
3. In orchestrated runs, opens product pages only for new IDs and one-time
   incomplete-item targets; the combined run has a shared safety cap
4. Confirms missing items via one product-page soft-delete check
5. Supports a PDP-only backfill for existing incomplete rows
6. Writes lean JSON (`schema_version: pcpmf_listing_catalog_v1`)
7. Optionally pushes those files to a **private** staging repository
8. Optionally triggers a private “bridge” workflow to consume staged JSON

## What it must never do

- Mention or call any production website ingest API
- Embed production API secrets / Bearer tokens for a live site
- Use a brand-identifying User-Agent

Identity User-Agent for GitHub / tooling: `ListingCatalogFetcher/0.1`.
HTML fetches use a browser-like User-Agent only where Cloudflare-style
protections require it (still anonymous; no site brand).

Before the first public push, review `git status` and do not force-add ignored
local experiments. Only the generic parser and runtime configuration contract
belong in this repository.

## Local run

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Dynamic single store
python -m src.fetch_all --out-dir .out \
  --inline-store example \
  --listing-url-template "https://example.com/search?page={page}" \
  --page-size 20

# Batch from JSON
python -m src.fetch_all --out-dir .out --stores-json path/to/stores.json
```

Store object fields (JSON):

| Field | Meaning |
|-------|---------|
| `key` | Retailer key (file name stem) |
| `platform` | `listing_html` |
| `listing_url_template` | URL with `{page}` placeholder |
| `page_size_hint` | Expected items per page |
| `min_page1_items` | Health fail if page 1 has fewer (default 10) |
| `max_pages` | Optional hard cap |
| `enrich_mode` | `targeted` for new/incomplete orchestration; empty for listing-only manual runs |
| `enrichment_state_blob` | Compressed private runtime state containing known and eligible IDs/URLs |
| `enrich_limit` | Cap for eligible PDP calls; `0` means all eligible targets |
| `pdp_only` | Process existing `enrich_items` without fetching listing pages |
| `enrich_items` | Existing item rows supplied by the private orchestrator for PDP-only backfill |
| `missing_targets` | Previously missing `{merchant_item_id, product_url}` rows eligible for one check |
| `card_selector` | CSS selector for one product card |
| `id_attribute` / `id_regex` | Where the stable shop item id is found |
| `title_selectors` / `url_selectors` | Ordered CSS selector lists |
| `price_selectors` / `sale_price_selectors` / `regular_price_selectors` | Price selector lists |
| `mpn_selectors` / `mpn_regex` | Optional mapping identifier selectors/pattern |
| `listing_implies_in_stock` | Use when the listing itself is an in-stock result |

## GitHub Actions

See `.github/workflows/fetch.yml`.

### Staging push (optional)

- `STAGING_PUSH_TOKEN` — fine-grained PAT with **contents: write** on the private staging repo
- `STAGING_REPO` — `owner/name`
- `STAGING_BRANCH` — usually `listing-incoming`

Listing JSON is not uploaded as a public Actions artifact. The private staging
branch is the only data hand-off.

Staging paths:

- `listing-bridge/incoming/{YYYY-MM-DD}/`
- `listing-bridge/incoming/latest/`

### Bridge trigger (optional)

- `BRIDGE_DISPATCH_TOKEN` — PAT with **actions: write** on the private bridge repo
- `BRIDGE_REPO` — `owner/name`
- `BRIDGE_WORKFLOW` — workflow file name (default `listing-bridge.yml`)
- `BRIDGE_REF` — git ref (default `main`)
- `BRIDGE_MODE` — ingest mode (default `dry_run`; set `apply` only when ready)
