"""Source classification.

Decides, from a URL and the seed it was discovered through, whether a page
is an official/primary source and which Atlas source-type bucket it falls
into. Aggregators are recognised explicitly so they can be used for
discovery while never being treated as authoritative.
"""

from __future__ import annotations

from urllib.parse import urlparse

AGGREGATOR_DOMAINS = {
    "buddy4study.com",
    "vidyasaarathi.co.in",
    "scholarshipsinindia.com",
    "collegedunia.com",
    "shiksha.com",
    "careers360.com",
    "getmyuni.com",
    "collegedekho.com",
    "apnaaddmission.com",
}

SOURCE_TYPES = [
    "Government",
    "University",
    "Corporate CSR",
    "NGO/Trust",
    "International",
    "Aggregator",
    "Other",
]


def registrable_domain(url: str) -> str:
    host = urlparse(url).netloc.lower().split(":")[0]
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    # handle common two-part public suffixes used in India/UK
    two_part = {"gov.in", "nic.in", "ac.in", "co.in", "org.in", "gov.uk", "ac.uk", "co.uk", "org.uk"}
    suffix = ".".join(parts[-2:])
    if suffix in two_part and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def is_aggregator(url: str) -> bool:
    return registrable_domain(url) in AGGREGATOR_DOMAINS


def classify_by_domain(url: str) -> str:
    """Fallback classification from the domain alone."""
    host = urlparse(url).netloc.lower()
    dom = registrable_domain(url)
    if is_aggregator(url):
        return "Aggregator"
    if host.endswith(".gov.in") or host.endswith(".nic.in") or dom in {"gov.in", "nic.in"}:
        return "Government"
    if host.endswith(".ac.in") or host.endswith(".edu") or host.endswith(".ac.uk"):
        return "University"
    if host.endswith(".gov") or host.endswith(".gov.uk") or host.endswith(".europa.eu"):
        return "International"
    if host.endswith(".org") or host.endswith(".org.in"):
        return "NGO/Trust"
    return "Other"


def is_official_source(url: str, seed_source_type: str) -> bool:
    """A source counts as official/primary when it is not an aggregator and
    it belongs to the provider's own domain family (government portal,
    provider organisation site, university site, official programme site)."""
    if is_aggregator(url):
        return False
    if seed_source_type == "Aggregator":
        return False
    return True


def same_domain_family(url_a: str, url_b: str) -> bool:
    return registrable_domain(url_a) == registrable_domain(url_b)
