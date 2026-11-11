from pathlib import Path

from src import extract as ex

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_date_numeric():
    assert ex.parse_date("31-10-2026") == "2026-10-31"
    assert ex.parse_date("01/06/2026") == "2026-06-01"


def test_parse_date_month_names():
    assert ex.parse_date("30 September 2026") == "2026-09-30"
    assert ex.parse_date("September 30, 2026") == "2026-09-30"
    assert ex.parse_date("15th Nov 2026") == "2026-11-15"


def test_parse_date_invalid():
    assert ex.parse_date("not a date") is None
    assert ex.parse_date("45-13-2026") is None


def test_detail_page_extraction():
    html = (FIXTURES / "detail_page.html").read_text()
    fields, evidence, links = ex.extract_detail_page(html, "Example Trust")
    assert fields["name"] == "Example Trust Merit Scholarship"
    assert fields["closing_date"] == "2026-09-30"
    assert fields["opening_date"] == "2026-08-01"
    assert "25,000" in fields["amount"]
    assert "75%" in fields["academic_requirements"]
    assert "3,50,000" in fields["income_criteria"]
    assert "Marksheet" in fields["documents_required"]
    assert "merit" in fields["selection_process"].lower()
    # Every populated field must carry evidence from the page
    for f in ("closing_date", "amount", "income_criteria"):
        assert evidence.get(f), f"missing evidence for {f}"


def test_missing_fields_are_not_specified_never_invented():
    html = (FIXTURES / "detail_page.html").read_text()
    fields, _, _ = ex.extract_detail_page(html, "Example Trust")
    # The fixture page states no age limit and no domicile rule, so the
    # extractor must leave them unspecified rather than guessing values.
    assert fields["age_criteria"] == ex.NOT_SPECIFIED
    assert fields["domicile"] == ex.NOT_SPECIFIED


def test_application_url_found():
    html = (FIXTURES / "detail_page.html").read_text()
    _, _, links = ex.extract_detail_page(html, "Example Trust")
    url = ex.find_application_url(links, "https://example.org/scholarship")
    assert url == "https://example.org/apply/example-merit"


def test_amount_is_not_the_income_limit():
    html = (FIXTURES / "amount_vs_income.html").read_text()
    fields, _, _ = ex.extract_detail_page(html, "Fixture Foundation")
    assert fields["amount"].startswith("Rs. 50,000")
    assert "8 lakh" in fields["income_criteria"]


def test_split_number_and_unit_repaired():
    lines = ["Stipend at the rate of £1,", "690 per month for scholars"]
    amount, _ = ex._extract_amount(lines)
    assert amount == "£1,690 per month"
    lines = ["Annual income should be less than", "Rs 4.00 Lacs"]
    fields, _ = ex.extract_from_lines(lines)
    assert "4.00" in fields["income_criteria"]


def test_nsp_listing_parser():
    html = (FIXTURES / "nsp_listing.html").read_text()
    cands = ex.parse_nsp_listing(html)
    assert len(cands) == 2
    first = cands[0]
    assert first["provider"] == "Ministry of Example Affairs"
    assert "Post Matric" in first["name"]
    assert first["opening_date"] == "2026-06-01"
    assert first["closing_date"] == "2026-10-31"
    assert first["guideline_url"].endswith("EXAMPLE_G.pdf")
    assert cands[1]["closing_date"] == "2026-11-30"
