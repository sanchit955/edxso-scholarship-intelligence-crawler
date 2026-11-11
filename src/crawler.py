"""Crawler pipeline: Discover -> Crawl -> Extract -> Verify -> Score ->
Store -> Update.

Usage:
    python -m src.crawler [--config config/seeds.json]
                          [--db data/scholarships.db]
                          [--export data/scholarships.json]

Each invocation is one crawl run. Records are keyed by their official
source URL; re-running re-fetches every known official source, snapshots
the newly extracted fields and records field-level changes instead of
overwriting history.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from . import extract as ex
from .classify import is_official_source, same_domain_family
from .discovery import discover_links
from .fetcher import Fetcher
from .scoring import score_record, verification_status
from .store import Store

NS = ex.NOT_SPECIFIED
_STOPWORDS = {
    "scholarship", "scheme", "for", "the", "of", "and", "based", "merit",
    "cum", "means", "students", "student", "programme", "program",
}


def _key(url: str) -> str:
    return url.split("#")[0].rstrip("/")


def name_present(name: str, text: str) -> bool:
    """True when most significant name tokens appear in the source text."""
    tokens = [
        t for t in re.split(r"[^a-z0-9]+", name.lower())
        if len(t) > 2 and t not in _STOPWORDS
    ]
    if not tokens:
        return False
    low = text.lower()
    hits = sum(1 for t in tokens if t in low)
    return hits / len(tokens) >= 0.7


def lifecycle_status(closing_iso: str, today: date) -> str:
    if closing_iso and closing_iso != NS:
        try:
            delta = (date.fromisoformat(closing_iso) - today).days
        except ValueError:
            return "ACTIVE"
        if delta < 0:
            return "EXPIRED"
        if delta <= 30:
            return "EXPIRING_SOON"
    return "ACTIVE"


def _traceability(fields: dict, evidence: dict) -> tuple[int, int]:
    populated = [f for f in ex.SCHEMA_FIELDS if fields.get(f) not in (None, "", NS)]
    evidenced = [f for f in populated if evidence.get(f)]
    return len(populated), len(evidenced)


class Crawler:
    def __init__(self, store: Store, fetcher: Fetcher):
        self.store = store
        self.fetcher = fetcher
        self.today = date.today()
        self.processed: set[str] = set()
        self.seen = 0
        self.new_count = 0
        self.changed_records = 0
        self.change_details: list[str] = []

    # -- shared save path -----------------------------------------------------
    def _save(self, run_id, *, key, fields, evidence, source_type, official_url,
              application_url, discovered_via, is_official, presence, fetched_ok,
              conflicts=0):
        populated, evidenced = _traceability(fields, evidence)
        app_official = bool(application_url) and (
            same_domain_family(application_url, official_url)
            or is_official_source(application_url, source_type)
        )
        score, components = score_record(
            is_official=is_official,
            presence_confirmed=presence,
            deadline_evidenced=bool(
                fields.get("closing_date") not in (None, "", NS)
                and evidence.get("closing_date")
            ),
            eligibility_evidenced=bool(
                fields.get("eligibility") not in (None, "", NS)
                and evidence.get("eligibility")
            ),
            application_url_official=app_official,
            fetched_ok=fetched_ok,
            conflicts=conflicts,
            populated_fields=populated,
            evidenced_fields=evidenced,
        )
        sid, is_new, changes = self.store.save_record(
            run_id=run_id,
            dedupe_key=key,
            fields=fields,
            evidence=evidence,
            source_type=source_type,
            official_source_url=official_url,
            application_url=application_url or "",
            discovered_via=discovered_via,
            confidence=score,
            score_components=components,
            lifecycle_status=lifecycle_status(fields.get("closing_date", ""), self.today),
            verification_status=verification_status(score),
        )
        self.processed.add(key)
        self.seen += 1
        if is_new:
            self.new_count += 1
        if changes:
            self.changed_records += 1
            for c in changes:
                self.change_details.append(
                    f"{fields.get('name', key)}: {c['field']} "
                    f"'{c['old_value']}' -> '{c['new_value']}'"
                )
        return sid

    # -- generic detail pages ---------------------------------------------------
    def process_detail_page(self, run_id, url, seed) -> bool:
        res = self.fetcher.fetch(url)
        if not res.ok:
            print(f"  [skip] fetch failed {url} ({res.error or res.status_code})")
            return False
        official_url = res.final_url or url
        is_pdf = "pdf" in res.content_type.lower() or res.content[:4] == b"%PDF"
        if is_pdf:
            # Providers often publish the scheme itself as an official PDF
            # document; mine it with the same field extractors.
            try:
                lines = ex.pdf_to_lines(res.content)
            except Exception as exc:
                print(f"  [skip] PDF parse failed {url}: {exc}")
                return False
            if not lines:
                return False
            fields, evidence = ex.extract_from_lines(lines)
            name = ""
            for ln in lines[:60]:
                if re.search(r"scholarship|fellowship", ln, re.I) and 12 <= len(ln) <= 130 and "http" not in ln:
                    name = ln
                    break
            if not name:
                print(f"  [skip] no programme name found in PDF: {url}")
                return False
            fields["name"] = name
            evidence["name"] = name
            fields["provider"] = seed["provider"]
            evidence["provider"] = seed["provider"]
            presence = name_present(name, " ".join(lines))
            app_url = ""
            full_text = " ".join(lines)
        else:
            if not res.text:
                print(f"  [skip] empty page {url}")
                return False
            fields, evidence, links = ex.extract_detail_page(res.text, seed["provider"])
            name = fields.get("name", "")
            _, _, lines, _ = ex.page_parts(res.text)
            presence = name_present(name, " ".join(lines))
            app_url = ex.find_application_url(links, official_url)
            full_text = res.text[:2000]
        has_signal = any(
            fields.get(f) not in (None, "", NS)
            for f in ("eligibility", "closing_date", "amount")
        )
        if len(name) < 8 or not has_signal or (
            "scholarship" not in (name + full_text).lower()
            and "fellowship" not in (name + full_text).lower()
        ):
            print(f"  [skip] not a scholarship page: {url}")
            return False
        self._save(
            run_id,
            key=_key(official_url),
            fields=fields,
            evidence=evidence,
            source_type=seed["source_type"],
            official_url=official_url,
            application_url=app_url,
            discovered_via=seed["url"],
            is_official=is_official_source(official_url, seed["source_type"]),
            presence=presence,
            fetched_ok=True,
        )
        print(f"  [ok] {name[:70]}")
        return True

    # -- NSP listing -------------------------------------------------------------
    def process_nsp(self, run_id, seed) -> None:
        res = self.fetcher.fetch(seed["url"])
        if not res.ok:
            print(f"  [error] NSP listing fetch failed: {res.error}")
            return
        candidates = ex.parse_nsp_listing(res.text)
        print(f"  discovered {len(candidates)} schemes on NSP listing")
        # Round-robin across ministries/departments for a balanced corpus
        by_provider: dict[str, list] = {}
        for c in candidates:
            by_provider.setdefault(c["provider"], []).append(c)
        selected: list[dict] = []
        while len(selected) < seed.get("max_records", 16):
            progressed = False
            for prov in by_provider:
                if by_provider[prov] and len(selected) < seed.get("max_records", 16):
                    selected.append(by_provider[prov].pop(0))
                    progressed = True
            if not progressed:
                break
        # The portal application entry point is linked from the portal's
        # own navigation, which the listing page itself carries.
        from urllib.parse import urljoin

        app_url = ""
        _, _, _, listing_links = ex.page_parts(res.text)
        for text, href in listing_links:
            if "apply for scholarship" in text.lower():
                app_url = urljoin(res.final_url or seed["url"], href)
                break
        if not app_url:
            home = self.fetcher.fetch("https://scholarships.gov.in/")
            if home.ok:
                _, _, _, links = ex.page_parts(home.text)
                for text, href in links:
                    if "apply for scholarship" in text.lower():
                        app_url = urljoin(home.final_url, href)
                        break
        for cand in selected:
            fields = {f: NS for f in ex.SCHEMA_FIELDS}
            evidence: dict[str, str] = {}
            fields["name"] = cand["name"]
            evidence["name"] = cand["listing_evidence"]
            fields["provider"] = cand["provider"]
            evidence["provider"] = cand["listing_evidence"]
            if cand["opening_date"]:
                fields["opening_date"] = cand["opening_date"]
                evidence["opening_date"] = cand["listing_evidence"]
            if cand["closing_date"]:
                fields["closing_date"] = cand["closing_date"]
                evidence["closing_date"] = cand["listing_evidence"]
            conflicts = 0
            presence = False
            fetched_ok = False
            pdf = self.fetcher.fetch(cand["guideline_url"])
            if pdf.ok and pdf.content:
                try:
                    lines = ex.pdf_to_lines(pdf.content)
                except Exception as exc:
                    print(f"  [warn] guideline PDF parse failed {cand['name'][:40]}: {exc}")
                    lines = []
                if lines:
                    fetched_ok = True
                    # Presence is confirmed when the name matches on the
                    # official guideline document or on the official portal
                    # listing the name was discovered from.
                    presence = name_present(
                        cand["name"],
                        " ".join(lines) + " " + cand["listing_evidence"],
                    )
                    pdf_fields, pdf_evidence = ex.extract_from_lines(lines)
                    for f, v in pdf_fields.items():
                        if v in (None, "", NS):
                            continue
                        if f in ("opening_date", "closing_date"):
                            # The live portal listing is authoritative for the
                            # current cycle; a different date in the guideline
                            # document counts as a conflict, not an overwrite.
                            if fields.get(f) not in (None, "", NS) and fields[f] != v:
                                conflicts += 1
                            elif fields.get(f) in (None, "", NS):
                                fields[f] = v
                                evidence[f] = pdf_evidence.get(f, "")
                            continue
                        if fields.get(f) in (None, "", NS):
                            fields[f] = v
                            if pdf_evidence.get(f):
                                evidence[f] = pdf_evidence[f]
            if not fetched_ok:
                # Presence is still evidenced by the official portal listing
                presence = True
            self._save(
                run_id,
                key=_key(cand["guideline_url"]),
                fields=fields,
                evidence=evidence,
                source_type="Government",
                official_url=cand["guideline_url"],
                application_url=app_url,
                discovered_via=seed["url"],
                is_official=True,
                presence=presence,
                fetched_ok=fetched_ok,
                conflicts=conflicts,
            )
            print(f"  [ok] {cand['name'][:70]}")

    # -- re-verification of previously known records ------------------------------
    def reverify_known(self, run_id) -> None:
        for row in self.store.all_records():
            key = row["dedupe_key"]
            if key in self.processed:
                continue
            url = row["official_source_url"]
            print(f"  re-verify: {row['name'][:60]}")
            res = self.fetcher.fetch(url)
            if not res.ok or (not res.text and not res.content):
                self.store.mark_no_longer_verifiable(
                    run_id, int(row["id"]),
                    f"Official source unreachable in run {run_id}: "
                    f"{res.error or res.status_code}",
                )
                self.processed.add(key)
                continue
            fields = {f: NS for f in ex.SCHEMA_FIELDS}
            evidence: dict[str, str] = {}
            if "pdf" in res.content_type.lower() or url.lower().endswith(".pdf"):
                try:
                    lines = ex.pdf_to_lines(res.content)
                except Exception:
                    lines = []
                pdf_fields, pdf_evidence = ex.extract_from_lines(lines)
                fields.update(pdf_fields)
                evidence.update(pdf_evidence)
                presence = name_present(row["name"], " ".join(lines))
                fields["name"] = row["name"]
                fields["provider"] = row["provider"]
                evidence.setdefault("name", row["name"])
            else:
                fields, evidence, links = ex.extract_detail_page(res.text, row["provider"])
                _, _, lines, _ = ex.page_parts(res.text)
                presence = name_present(fields.get("name", row["name"]), " ".join(lines))
                app_url = ex.find_application_url(links, res.final_url or url)
                if app_url:
                    pass
                else:
                    app_url = row["application_url"] or ""
                fields["provider"] = row["provider"]
                self._save(
                    run_id, key=key, fields=fields, evidence=evidence,
                    source_type=row["source_type"], official_url=url,
                    application_url=app_url, discovered_via="re-verification",
                    is_official=is_official_source(url, row["source_type"]),
                    presence=presence, fetched_ok=True,
                )
                continue
            self._save(
                run_id, key=key, fields=fields, evidence=evidence,
                source_type=row["source_type"], official_url=url,
                application_url=row["application_url"] or "",
                discovered_via="re-verification",
                is_official=is_official_source(url, row["source_type"]),
                presence=presence, fetched_ok=True,
            )


def run_crawl(config_path: str, db_path: str, export_path: str | None) -> dict:
    config = json.loads(Path(config_path).read_text())
    store = Store(db_path)
    fetcher = Fetcher()
    crawler = Crawler(store, fetcher)
    run_id = store.start_run()
    print(f"=== Crawl run {run_id} started ===")
    for seed in config["seeds"]:
        print(f"Seed [{seed['id']}] {seed['url']}")
        if seed["kind"] == "nsp_listing":
            crawler.process_nsp(run_id, seed)
        elif seed["kind"] == "link_index":
            res = fetcher.fetch(seed["url"])
            if not res.ok:
                print(f"  [error] index fetch failed: {res.error or res.status_code}")
                continue
            candidates = discover_links(
                res.text, res.final_url or seed["url"],
                limit=seed.get("max_records", 5) * 2,
            )
            print(f"  discovered {len(candidates)} candidate pages")
            if not candidates:
                # Some providers publish a single programme on the index
                # page itself; evaluate the page as a detail page (the
                # content gate in process_detail_page still applies).
                print("  no outbound candidates; evaluating the index page itself")
                crawler.process_detail_page(run_id, seed["url"], seed)
            accepted = 0
            for cand in candidates:
                if accepted >= seed.get("max_records", 5):
                    break
                if _key(cand["url"]) in crawler.processed:
                    accepted += 1
                    continue
                if crawler.process_detail_page(run_id, cand["url"], seed):
                    accepted += 1
    print("Re-verifying previously known records not rediscovered...")
    crawler.reverify_known(run_id)
    store.finish_run(run_id, crawler.seen, crawler.new_count, crawler.changed_records)
    stats = store.stats()
    print(f"=== Run {run_id} finished ===")
    print(json.dumps(stats, indent=2))
    if crawler.change_details:
        print("Changes detected this run:")
        for line in crawler.change_details:
            print("  -", line)
    if export_path:
        records = store.export_records()
        Path(export_path).parent.mkdir(parents=True, exist_ok=True)
        Path(export_path).write_text(json.dumps(records, indent=2, ensure_ascii=False))
        print(f"Exported {len(records)} records to {export_path}")
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="Scholarship Intelligence Crawler")
    ap.add_argument("--config", default="config/seeds.json")
    ap.add_argument("--db", default="data/scholarships.db")
    ap.add_argument("--export", default="data/scholarships.json")
    args = ap.parse_args()
    run_crawl(args.config, args.db, args.export)


if __name__ == "__main__":
    main()
