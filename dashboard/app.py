"""Scholarship Intelligence dashboard.

Reads the SQLite database produced by the crawler and shows headline
metrics, a searchable scholarship list, and a per-scholarship detail view
with the confidence breakdown ("Why this score?"), change history and
the source evidence behind every field.

Run:  streamlit run dashboard/app.py
"""

import json
import sqlite3
from pathlib import Path

import streamlit as st

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "scholarships.db"

st.set_page_config(page_title="Scholarship Intelligence", layout="wide")


@st.cache_data(ttl=30)
def load_records():
    if not DB_PATH.exists():
        return [], {}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM scholarships ORDER BY confidence DESC").fetchall()
    records = []
    for row in rows:
        rec = dict(row)
        rec["fields"] = json.loads(rec.get("fields_json") or "{}")
        rec["components"] = json.loads(rec.get("score_components") or "[]")
        rec["evidence"] = [dict(r) for r in conn.execute(
            "SELECT field, value, evidence, source_url FROM field_evidence "
            "WHERE scholarship_id=? AND run_id=(SELECT MAX(run_id) FROM field_evidence "
            "WHERE scholarship_id=?) ORDER BY field",
            (row["id"], row["id"]),
        ).fetchall()]
        rec["changes"] = [dict(r) for r in conn.execute(
            "SELECT field, old_value, new_value, detected_at, source_url, evidence "
            "FROM changes WHERE scholarship_id=? ORDER BY id",
            (row["id"],),
        ).fetchall()]
        records.append(rec)
    stats = {}
    if records:
        stats = {
            "total": len(records),
            "verified": sum(1 for r in records if r["verification_status"] == "VERIFIED"),
            "review": sum(1 for r in records if r["verification_status"] != "VERIFIED"),
            "active": sum(1 for r in records if r["lifecycle_status"] == "ACTIVE"),
            "expiring": sum(1 for r in records if r["lifecycle_status"] == "EXPIRING_SOON"),
            "expired": sum(1 for r in records if r["lifecycle_status"] == "EXPIRED"),
            "avg_conf": round(sum(r["confidence"] for r in records) / len(records), 1),
            "recent": sum(1 for r in records if r["last_seen_run"] == max(x["last_seen_run"] for x in records)),
        }
    conn.close()
    return records, stats


records, stats = load_records()

st.title("Scholarship Intelligence")
st.caption("Atlas Funding prototype — repository maintained by the Scholarship Intelligence Crawler")

if not records:
    st.warning("No crawl data yet. Run `python -m src.crawler` first.")
    st.stop()

c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
c1.metric("Total discovered", stats["total"])
c2.metric("Verified", stats["verified"])
c3.metric("Review required", stats["review"])
c4.metric("Active", stats["active"])
c5.metric("Expiring soon", stats["expiring"])
c6.metric("Expired", stats["expired"])
c7.metric("Avg confidence", f"{stats['avg_conf']}%")

st.subheader("Scholarships")
query = st.text_input("Search by name, provider, type or status", "")
filtered = [
    r for r in records
    if query.lower() in (
        f"{r['name']} {r['provider']} {r['source_type']} "
        f"{r['lifecycle_status']} {r['verification_status']}"
    ).lower()
]
st.dataframe(
    [
        {
            "Name": r["name"],
            "Provider": r["provider"],
            "Type": r["source_type"],
            "Amount": r["fields"].get("amount", "Not specified"),
            "Closing date": r["fields"].get("closing_date", "Not specified"),
            "Status": r["lifecycle_status"],
            "Verification": r["verification_status"],
            "Confidence": r["confidence"],
        }
        for r in filtered
    ],
    use_container_width=True,
)

st.subheader("Scholarship details")
names = [r["name"] for r in records]
selected = st.selectbox("Open a scholarship", names)
rec = next(r for r in records if r["name"] == selected)

left, right = st.columns([2, 1])
with left:
    st.markdown(f"### {rec['name']}")
    st.write(f"**Provider:** {rec['provider']}")
    for label, field in [
        ("Amount / benefit", "amount"),
        ("Eligibility", "eligibility"),
        ("Academic requirements", "academic_requirements"),
        ("Course / level", "course_level"),
        ("Income criteria", "income_criteria"),
        ("Age criteria", "age_criteria"),
        ("Gender criteria", "gender_criteria"),
        ("Category criteria", "category_criteria"),
        ("Domicile", "domicile"),
        ("Institution requirements", "institution_requirements"),
        ("Opening date", "opening_date"),
        ("Closing date", "closing_date"),
        ("Documents required", "documents_required"),
        ("Selection process", "selection_process"),
        ("Renewal requirements", "renewal_requirements"),
    ]:
        st.write(f"**{label}:** {rec['fields'].get(field, 'Not specified')}")
    st.write(f"**Official source:** {rec['official_source_url']}")
    if rec["application_url"]:
        st.write(f"**Application link:** {rec['application_url']}")
    st.write(f"**Last verified:** {rec['last_verified_at']}")

with right:
    st.metric("Confidence score", f"{rec['confidence']}%")
    st.write(f"**Status:** {rec['lifecycle_status']}")
    st.write(f"**Verification:** {rec['verification_status']}")
    st.markdown("#### Why this score?")
    for comp in rec["components"]:
        st.write(
            f"- {comp['rule']}: **{comp['points']}/{comp['max_points']}** — {comp['detail']}"
        )

st.markdown("#### Change history")
if rec["changes"]:
    for ch in rec["changes"]:
        st.write(
            f"- `{ch['field']}`: '{ch['old_value']}' → '{ch['new_value']}' "
            f"(detected {ch['detected_at']})"
        )
else:
    st.write("No changes detected yet.")

st.markdown("#### Source evidence")
if rec["evidence"]:
    for ev in rec["evidence"]:
        st.write(f"- **{ev['field']}** = {ev['value']}")
        st.caption(f"Evidence: {ev['evidence']}  ·  Source: {ev['source_url']}")
else:
    st.write("No evidence stored.")
