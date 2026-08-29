"""Browser-like HTML fetch with polite delay (cloudscraper)."""

from __future__ import annotations

import random
import time
from typing import Optional

import cloudscraper
from tenacity import retry, stop_after_attempt, wait_exponential

# Browser-like pool for Cloudflare-style pages. Project identity UA lives in src.USER_AGENT.
DEFAULT_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]


def polite_delay(min_seconds: float = 1.5, max_seconds: float = 3.5) -> None:
    lo = float(min_seconds)
    hi = float(max_seconds)
    if hi < lo:
        lo, hi = hi, lo
    time.sleep(random.uniform(lo, hi))


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20), reraise=True)
def fetch_html(
    url: str,
    *,
    timeout: int = 60,
    delay_min: float = 1.5,
    delay_max: float = 3.5,
    pause_after: Optional[float] = None,
) -> tuple[int, str, str]:
    """Return (status_code, final_url, html_text). Always applies a polite pause after."""
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
    headers = {
        "User-Agent": random.choice(DEFAULT_UA_POOL),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }
    resp = scraper.get(url, headers=headers, timeout=timeout)
    if pause_after is not None:
        if pause_after > 0:
            time.sleep(pause_after)
    else:
        polite_delay(delay_min, delay_max)
    return resp.status_code, str(resp.url), resp.text
