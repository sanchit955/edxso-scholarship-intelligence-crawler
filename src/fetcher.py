"""HTTP fetching with politeness controls: retries, backoff, per-domain delay.

All crawling goes through this module so that rate behaviour is consistent
and every fetch result carries the metadata the verification engine needs
(final URL after redirects, HTTP status, content type, fetch timestamp).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
MAX_BYTES = 12 * 1024 * 1024  # refuse absurdly large downloads
_last_fetch_by_domain: dict[str, float] = {}


@dataclass
class FetchResult:
    url: str
    final_url: str = ""
    status_code: int = 0
    content_type: str = ""
    text: str = ""
    content: bytes = b""
    error: str = ""
    fetched_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def ok(self) -> bool:
        return self.status_code == 200 and not self.error


class Fetcher:
    def __init__(self, min_delay: float = 1.2, retries: int = 2, timeout: int = 25):
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": USER_AGENT, "Accept-Language": "en-IN,en;q=0.8"}
        )
        self.min_delay = min_delay
        self.retries = retries
        self.timeout = timeout

    def _polite_wait(self, url: str) -> None:
        domain = urlparse(url).netloc
        last = _last_fetch_by_domain.get(domain, 0.0)
        wait = self.min_delay - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        _last_fetch_by_domain[domain] = time.time()

    def fetch(self, url: str) -> FetchResult:
        result = FetchResult(url=url)
        backoff = 2.0
        for attempt in range(1, self.retries + 1):
            self._polite_wait(url)
            try:
                resp = self.session.get(url, timeout=self.timeout, stream=True)
                raw = resp.raw.read(MAX_BYTES + 1, decode_content=True) or b""
                result.status_code = resp.status_code
                result.final_url = resp.url
                result.content_type = resp.headers.get("Content-Type", "")
                if len(raw) > MAX_BYTES:
                    result.error = "response exceeded size limit"
                    return result
                result.content = raw
                if "pdf" not in result.content_type.lower():
                    result.text = raw.decode(
                        resp.encoding or "utf-8", errors="replace"
                    )
                if resp.status_code == 200:
                    result.error = ""
                    return result
                result.error = f"HTTP {resp.status_code}"
            except requests.RequestException as exc:
                result.error = f"{type(exc).__name__}: {exc}"
            if attempt < self.retries:
                time.sleep(backoff)
                backoff *= 2.5
        return result
