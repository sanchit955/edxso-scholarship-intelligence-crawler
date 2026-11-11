"""Discovery: turn listing/index pages into candidate scholarship pages.

Seeds are index pages only. Candidates are links found on those pages
whose anchor text or URL indicates a scholarship/fellowship/scheme, kept
on the provider's own domain family so discovery stays on official sites.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .classify import registrable_domain

_KEYWORDS = re.compile(
    r"scholarship|fellowship|fellow|scheme|grant|bursary|studentship|award",
    re.I,
)
_EXCLUDE = re.compile(
    r"login|sign-in|sign in|register|privacy|terms|cookie|contact|faq|"
    r"sitemap|careers|jobs|press|news|blog|facebook|twitter|instagram|"
    r"linkedin|youtube|donate",
    re.I,
)


def discover_links(html: str, base_url: str, limit: int = 12) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    base_dom = registrable_domain(base_url)
    seen: set[str] = set()
    candidates: list[dict] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full = urljoin(base_url, href)
        if not full.startswith("http"):
            continue
        if registrable_domain(full) != base_dom:
            continue
        path = urlparse(full).path.lower()
        if path.endswith((".pdf", ".jpg", ".png", ".zip", ".doc", ".docx")):
            continue
        text = re.sub(r"\s+", " ", a.get_text() or "").strip()
        signal = f"{text} {path}"
        if not _KEYWORDS.search(signal):
            continue
        if _EXCLUDE.search(text.lower()) and len(text) < 40:
            continue
        key = full.rstrip("/")
        if key in seen or key == base_url.rstrip("/"):
            continue
        seen.add(key)
        # Prefer anchors with descriptive text (likely real programme pages)
        score = len(text) + (20 if "scholarship" in path else 0)
        candidates.append({"url": full, "anchor": text[:120], "score": score})
    candidates.sort(key=lambda c: -c["score"])
    return candidates[:limit]
