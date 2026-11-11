"""Render docs/TECHNICAL_NOTE.md to docs/TECHNICAL_NOTE.pdf (max 3 pages).

Uses fpdf2's markdown support (**bold**) inside multi_cell. Kept
deliberately small: headings, paragraphs and numbered/bulleted lines.
"""

from pathlib import Path

from fpdf import FPDF

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "TECHNICAL_NOTE.md"
DST = ROOT / "docs" / "TECHNICAL_NOTE.pdf"

# The built-in Helvetica core font is Latin-1; map common typographic
# characters onto equivalents it can render.
_SANITISE = {
    "\u2014": " -- ",
    "\u2013": "-",
    "\u2192": "->",
    "\u2265": ">=",
    "\u2264": "<=",
    "\u00b7": "-",
    "\u201c": '"',
    "\u201d": '"',
    "\u2018": "'",
    "\u2019": "'",
    "\u20b9": "Rs.",
}


def _clean(text: str) -> str:
    for src, dst in _SANITISE.items():
        text = text.replace(src, dst)
    return text.replace("`", "")


def main() -> None:
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.set_margins(18, 16, 18)
    pdf.add_page()
    for raw in SRC.read_text().split("\n"):
        line = raw.strip()
        if not line:
            pdf.ln(2.2)
            continue
        if line.startswith("# "):
            pdf.set_font("helvetica", "B", 15)
            pdf.multi_cell(0, 7.5, _clean(line[2:]), markdown=True)
            pdf.ln(1.5)
        elif line.startswith("## "):
            pdf.set_font("helvetica", "B", 11.5)
            pdf.multi_cell(0, 6, _clean(line[3:]), markdown=True)
            pdf.ln(0.8)
        else:
            pdf.set_font("helvetica", "", 10.3)
            pdf.multi_cell(0, 5.1, _clean(line), markdown=True)
            pdf.ln(0.7)
    pdf.output(DST)
    print(f"wrote {DST} with {pdf.pages_count} page(s)")


if __name__ == "__main__":
    main()
