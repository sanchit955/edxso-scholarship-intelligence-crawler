"""Rule-based field extraction with per-field evidence.

Every value placed into a scholarship record is copied from text that was
actually fetched from the source page, and the exact snippet it came from
is stored alongside it. Fields the source does not state are left as
"Not specified" -- values are never inferred or generated.
"""

from __future__ import annotations

import io
import re
from datetime import date

from bs4 import BeautifulSoup

NOT_SPECIFIED = "Not specified"

SCHEMA_FIELDS = [
    "name",
    "provider",
    "amount",
    "eligibility",
    "academic_requirements",
    "course_level",
    "income_criteria",
    "age_criteria",
    "gender_criteria",
    "category_criteria",
    "domicile",
    "institution_requirements",
    "opening_date",
    "closing_date",
    "documents_required",
    "selection_process",
    "renewal_requirements",
]

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_DATE_PATTERNS = [
    re.compile(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b"),
    re.compile(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\.?\s*,?\s*(\d{4})\b"
    ),
    re.compile(
        r"\b([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(\d{4})\b"
    ),
]


def parse_date(raw: str) -> str | None:
    """Parse one date string to ISO format, or return None."""
    raw = raw.strip()
    m = _DATE_PATTERNS[0].match(raw)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            return None
    m = _DATE_PATTERNS[1].match(raw)
    if m:
        mon = MONTHS.get(m.group(2).lower().rstrip("."))
        if mon:
            try:
                return date(int(m.group(3)), mon, int(m.group(1))).isoformat()
            except ValueError:
                return None
    m = _DATE_PATTERNS[2].match(raw)
    if m:
        mon = MONTHS.get(m.group(1).lower().rstrip("."))
        if mon:
            try:
                return date(int(m.group(3)), mon, int(m.group(2))).isoformat()
            except ValueError:
                return None
    return None


def find_dates(text: str) -> list[tuple[str, str]]:
    """All (iso, raw) date pairs in a text fragment, in order of appearance."""
    found: list[tuple[str, str]] = []
    for pat in _DATE_PATTERNS:
        for m in pat.finditer(text):
            iso = parse_date(m.group(0))
            if iso:
                found.append((m.start(), iso, m.group(0)))
    found.sort()
    out, seen = [], set()
    for _, iso, raw in found:
        if iso not in seen:
            seen.add(iso)
            out.append((iso, raw))
    return out


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _clip(text: str, limit: int = 300) -> str:
    text = _clean(text)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def page_parts(html: str):
    """Split an HTML page into (title, h1, text lines, links)."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    title = _clean(soup.title.get_text()) if soup.title else ""
    h1_tag = soup.find("h1")
    h1 = _clean(h1_tag.get_text()) if h1_tag else ""
    raw_text = soup.get_text("\n")
    lines = [_clean(ln) for ln in raw_text.split("\n")]
    lines = [ln for ln in lines if len(ln) >= 2]
    links = []
    for a in soup.find_all("a", href=True):
        links.append((_clean(a.get_text()), a["href"]))
    return title, h1, lines, links


def _section(lines: list[str], keywords: list[str], max_lines: int = 10) -> str:
    """Text block following a heading line that matches one of keywords."""
    for i, ln in enumerate(lines):
        low = ln.lower()
        if len(ln) <= 60 and any(k in low for k in keywords):
            collected = []
            for nxt in lines[i + 1 : i + 1 + max_lines]:
                if (
                    len(nxt) <= 55
                    and nxt[-1] not in ".:;"
                    and not nxt[0].isdigit()
                    and len(collected) >= 2
                    and re.search(
                        r"(eligib|document|selection|amount|benefit|how to|about|faq|contact)",
                        nxt.lower(),
                    )
                ):
                    break
                collected.append(nxt)
            if collected:
                return _clip(" ".join(collected), 700)
    return ""


def _first_line_with(lines: list[str], *patterns: str) -> str:
    for ln in lines:
        low = ln.lower()
        if all(p in low for p in patterns):
            return ln
    return ""


_CURRENCY = re.compile(
    r"(?:₹|Rs\.?|INR)\s?[\d,]+(?:\.\d+)?(?:\s?(?:lakh|Lakh|Lacs|lacs|crore|Crore|crores|/-))?"
    r"(?:\s?per\s(?:annum|year|month))?"
    r"|(?:\$|£|€)\s?[\d,]+(?:\.\d+)?(?:\s?per\s(?:annum|year|month))?",
)


def _amount_magnitude(text: str) -> float:
    m = re.search(r"[\d,]+(?:\.\d+)?", text)
    if not m:
        return 0.0
    value = float(m.group(0).replace(",", ""))
    low = text.lower()
    if "crore" in low:
        value *= 1e7
    elif "lakh" in low:
        value *= 1e5
    return value


def _extract_amount(lines: list[str]) -> tuple[str, str]:
    best, best_score, best_line = "", -1, ""
    for i, ln in enumerate(lines):
        m = _CURRENCY.search(ln)
        if not m:
            continue
        phrase = m.group(0)
        # Page text extraction can split a number across lines
        # ("£1," / "690 per month"): rejoin the continuation digits.
        if i + 1 < len(lines) and phrase.rstrip()[-1] in ",0123456789":
            nxt = lines[i + 1]
            cont = re.match(r"^[\d,]+(?:\.\d+)?", nxt)
            if cont and phrase.rstrip().endswith(","):
                phrase = phrase + cont.group(0)
                tail = nxt[cont.end():].strip()
                per = re.match(r"(?i)(per\s(?:annum|year|month))", tail)
                if per:
                    phrase += " " + per.group(1)
        # A unit word (lakh/crore) may sit on the following line when the
        # page wraps text; reattach it so "Rs 4.00" + "lakh" stays whole.
        join_at = i + 1
        if join_at < len(lines) and re.match(r"(?i)^(lakh|lacs|crore|crores)\b", lines[join_at]):
            phrase = f"{phrase} {lines[join_at].split()[0]}"
        low = ln.lower()
        score = 0
        for kw in ("amount", "award", "stipend", "financial assistance",
                   "scholarship of", "grant of", "fellowship of", "value of",
                   "per annum", "per year", "maintenance allowance"):
            if kw in low:
                score += 2
        if "tuition" in low:
            score += 1
        if _amount_magnitude(phrase) >= 10000:
            score += 2
        # A currency figure inside an income-criterion statement is the
        # income limit, not the scholarship amount. The statement may
        # span lines ("Annual income should be less than" / "Rs 4.00
        # Lacs"), so the two preceding lines count as context too.
        context = " ".join(lines[max(0, i - 2) : i]).lower()
        if "income" in low or "income" in context:
            score -= 6
        if score > best_score:
            best, best_score, best_line = phrase, score, ln
    if best:
        return _clip(best.rstrip(" ,."), 120), _clip(best_line, 300)
    return "", ""


def _extract_dated_field(lines: list[str], keywords: list[str]) -> tuple[str, str]:
    for i, ln in enumerate(lines):
        low = ln.lower()
        if any(k in low for k in keywords):
            dates = find_dates(ln)
            if dates:
                return dates[0][0], _clip(ln, 300)
            # Label and date are often in adjacent elements (table cells,
            # definition lists): check the next two lines before giving up.
            for nxt in lines[i + 1 : i + 3]:
                dates = find_dates(nxt)
                if dates:
                    return dates[0][0], _clip(f"{ln} {nxt}", 300)
    return "", ""


def extract_from_lines(lines: list[str]) -> tuple[dict, dict]:
    """Generic field extraction over text lines.

    Returns (fields, evidence): fields maps schema field -> value or
    NOT_SPECIFIED; evidence maps field -> source snippet it was taken from.
    """
    fields: dict[str, str] = {}
    evidence: dict[str, str] = {}

    def put(field: str, value: str, ev: str = "") -> None:
        if value:
            fields[field] = value
            if ev:
                evidence[field] = ev
        else:
            fields[field] = NOT_SPECIFIED

    # --- dates -------------------------------------------------------------
    closing, ev = _extract_dated_field(
        lines,
        ["last date", "closing date", "deadline", "apply by", "applications close",
         "closed on", "open till", "submission of application"],
    )
    put("closing_date", closing, ev)
    opening, ev = _extract_dated_field(
        lines,
        ["applications open", "opening date", "apply from", "open from",
         "applications are invited from", "submission window opens"],
    )
    if not opening:
        opening, ev = _extract_dated_field(lines, ["start date"])
    put("opening_date", opening, ev)

    # --- amount ------------------------------------------------------------
    amount, ev = _extract_amount(lines)
    put("amount", amount, ev)

    # --- eligibility block -------------------------------------------------
    elig = _section(lines, ["eligibility", "who can apply", "who is eligible"])
    if not elig:
        ln = _first_line_with(lines, "eligible")
        elig = _clip(ln, 700) if ln else ""
    put("eligibility", elig, elig)

    search_space = [elig] + lines if elig else lines

    # --- income ------------------------------------------------------------
    income_value = ""
    for j, cand in enumerate(search_space):
        if "income" not in cand.lower():
            continue
        if _CURRENCY.search(cand) or "lakh" in cand.lower():
            income_value = cand
            break
        # Label and figure are often on separate lines ("Annual income
        # should be less than" / "Rs 4.00 Lacs"): look ahead briefly.
        for nxt in search_space[j + 1 : j + 3]:
            if _CURRENCY.search(nxt):
                income_value = f"{cand} {nxt}"
                break
        if income_value:
            break
    put("income_criteria", income_value, income_value)

    # --- academic requirements ---------------------------------------------
    ln = ""
    for cand in search_space:
        if re.search(r"\d{1,3}\s?%", cand) and re.search(
            r"mark|aggregate|score|secured|obtained", cand.lower()
        ):
            ln = cand
            break
    put("academic_requirements", ln, ln)

    # --- course / education level ------------------------------------------
    levels = []
    level_ev = ""
    joined = " ".join(search_space).lower()
    for label, pat in [
        ("School (Class 1-10)", r"class\s?(?:[1-9]|10)\b|class\s?(?:i|x)\b"),
        ("Higher Secondary (Class 11-12)", r"class\s?(?:11|12|xi|xii)\b|10\+2"),
        ("Undergraduate", r"undergraduat|bachelor"),
        ("Postgraduate", r"postgraduat|master'?s"),
        ("PhD / Doctoral", r"ph\.?d|doctoral"),
        ("Diploma / ITI", r"diploma|\biti\b"),
        ("Professional courses", r"\bmbbs\b|\bbds\b|engineering|b\.?tech|b\.?e\.?\b"),
    ]:
        if re.search(pat, joined):
            levels.append(label)
            if not level_ev:
                level_ev = _first_line_with(
                    search_space, *[w for w in pat.split("|")][:1]
                ) or (elig[:300] if elig else "")
    put("course_level", "; ".join(levels), _clip(level_ev, 300))

    # --- age ---------------------------------------------------------------
    ln = ""
    for cand in search_space:
        if "age" in cand.lower() and re.search(r"\d{1,2}\s?(?:years|yrs)", cand):
            ln = cand
            break
    put("age_criteria", ln, ln)

    # --- gender ------------------------------------------------------------
    ln = ""
    for cand in search_space:
        low = cand.lower()
        if re.search(r"only for girls|girl students|for women|female students|single girl child", low):
            ln = cand
            break
    put("gender_criteria", ln, ln)

    # --- category ----------------------------------------------------------
    ln = ""
    for cand in search_space:
        if re.search(
            r"\bsc\b|\bst\b|\bobc\b|\bews\b|scheduled caste|scheduled tribe|minority|minorities|denotified|persons with disabilit",
            cand.lower(),
        ):
            ln = cand
            break
    put("category_criteria", ln, ln)

    # --- domicile ----------------------------------------------------------
    ln = _first_line_with(search_space, "domicile") or _first_line_with(
        search_space, "permanent resident"
    )
    put("domicile", ln, ln)

    # --- institution requirements ------------------------------------------
    ln = ""
    for cand in search_space:
        low = cand.lower()
        if re.search(r"aicte|ugc recogn|recognised institution|recognized institution|enrolled in|studying in", low):
            ln = cand
            break
    put("institution_requirements", ln, ln)

    # --- documents ---------------------------------------------------------
    docs = _section(lines, ["documents required", "documents needed", "list of documents"])
    put("documents_required", docs, docs)

    # --- selection ---------------------------------------------------------
    sel = _section(lines, ["selection process", "selection criteria", "mode of selection"])
    put("selection_process", sel, sel)

    # --- renewal -----------------------------------------------------------
    ln = _first_line_with(lines, "renewal") or _first_line_with(lines, "renewable")
    put("renewal_requirements", ln, ln)

    return fields, evidence


def extract_detail_page(html: str, provider_hint: str = "") -> tuple[dict, dict, list]:
    """Extract a record from a scholarship detail page.

    Returns (fields, evidence, links)."""
    title, h1, lines, links = page_parts(html)
    fields, evidence = extract_from_lines(lines)
    name = h1
    if name.lower() in {"scholarships", "scholarship", "home", "welcome", ""}:
        # A generic heading carries no programme name; fall back to the
        # page title's first segment.
        name = title.split("|")[0].split("–")[0].strip()
    name = _clip(name, 160)
    if name:
        fields["name"] = name
        evidence["name"] = name
    else:
        fields["name"] = NOT_SPECIFIED
    fields["provider"] = provider_hint or NOT_SPECIFIED
    if provider_hint:
        evidence["provider"] = provider_hint
    return fields, evidence, links


def pdf_to_lines(content: bytes, max_pages: int = 25) -> list[str]:
    """Extract text lines from a PDF document (official guideline files)."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    lines: list[str] = []
    for page in reader.pages[:max_pages]:
        try:
            text = page.extract_text() or ""
        except Exception:
            continue
        for ln in text.split("\n"):
            ln = _clean(ln)
            if len(ln) >= 2:
                lines.append(ln)
    return lines


def find_application_url(links: list, page_url: str) -> str:
    """Pick the most plausible official application link from a page."""
    from urllib.parse import urljoin, urlparse

    best = ""
    for text, href in links:
        low = text.lower()
        full = urljoin(page_url, href)
        if not full.startswith("http"):
            continue
        if re.search(r"apply now|apply online|online application|application form|click here to apply", low):
            return full
        if "apply" in low and not best:
            best = full
        if "apply" in urlparse(full).path.lower() and not best:
            best = full
    return best


# ---------------------------------------------------------------------------
# National Scholarship Portal listing
# ---------------------------------------------------------------------------

_NSP_DATE_RE = re.compile(
    r"(?:Open from|Open till|Closed on|Open)\s*:?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{4})",
    re.I,
)


def parse_nsp_listing(html: str) -> list[dict]:
    """Parse the NSP 'All Scholarships' listing into scheme candidates.

    Each candidate carries the name, the ministry/department (provider),
    opening and closing dates exactly as printed on the portal, and the
    URL of the official scheme guideline document published by the portal.
    """
    soup = BeautifulSoup(html, "lxml")
    candidates: list[dict] = []
    for item in soup.select("div.accordion-item"):
        header = item.select_one(".accordion-button, .accordion-header")
        provider = _clean(header.get_text()) if header else ""
        provider = re.sub(r"\s+", " ", provider).strip(" -–")
        for row in item.select("div.row"):
            spec = row.find(
                "a", href=lambda h: h and "schemeGuidelines" in h
            )
            if not spec:
                continue
            text = row.get_text("\n")
            lines = [_clean(ln) for ln in text.split("\n") if _clean(ln)]
            name_lines = []
            for ln in lines:
                if re.match(r"(?i)scheme\s+open\s+from", ln):
                    break
                if ln.lower() in {"specifications", "faq"}:
                    continue
                name_lines.append(ln)
            name = _clip(" ".join(name_lines), 180)
            if len(name) < 8:
                continue
            joined = " ".join(lines)
            opening = ""
            closing = ""
            # Labels may carry a qualifier, e.g. "Open till (for Renewal):"
            m = re.search(
                r"(?i)open\s+from(?:\s*\([^)]*\))?\s*:?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{4})",
                joined,
            )
            if m:
                opening = parse_date(m.group(1)) or ""
            m = re.search(
                r"(?i)student\s+application\s+(?:closed\s+on|open\s+till)(?:\s*\([^)]*\))?\s*:?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{4})",
                joined,
            )
            if m:
                closing = parse_date(m.group(1)) or ""
            faq = row.find("a", href=lambda h: h and h.endswith(".pdf") and "schemeGuidelines" in h and h != spec["href"])
            candidates.append(
                {
                    "name": name.title() if name.isupper() else name,
                    "provider": provider,
                    "opening_date": opening,
                    "closing_date": closing,
                    "guideline_url": spec["href"],
                    "faq_url": faq["href"] if faq else "",
                    "listing_evidence": _clip(joined, 300),
                }
            )
    return candidates
