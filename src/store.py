"""SQLite storage: current records, per-run snapshots, evidence, changes.

History is append-only: a re-crawl adds a new snapshot and, when a field
differs from the previous snapshot, a row in `changes` holding both the
old and the new value. Current values in `scholarships` are a view of the
latest snapshot, never the only copy.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"

# Fields compared between snapshots for change detection.
COMPARABLE_FIELDS = [
    "name", "provider", "amount", "eligibility", "academic_requirements",
    "course_level", "income_criteria", "age_criteria", "gender_criteria",
    "category_criteria", "domicile", "institution_requirements",
    "opening_date", "closing_date", "documents_required", "selection_process",
    "renewal_requirements",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_hash(fields: dict) -> str:
    blob = json.dumps(fields, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class Store:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_PATH.read_text())
        self.conn.commit()

    # -- runs ---------------------------------------------------------------
    def start_run(self) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (started_at) VALUES (?)", (_now(),)
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, seen: int, new: int, changed: int, notes: str = ""):
        self.conn.execute(
            "UPDATE runs SET finished_at=?, records_seen=?, new_records=?, "
            "changed_records=?, notes=? WHERE id=?",
            (_now(), seen, new, changed, notes, run_id),
        )
        self.conn.commit()

    # -- records --------------------------------------------------------------
    def get_by_key(self, dedupe_key: str):
        return self.conn.execute(
            "SELECT * FROM scholarships WHERE dedupe_key=?", (dedupe_key,)
        ).fetchone()

    def all_records(self):
        return self.conn.execute("SELECT * FROM scholarships").fetchall()

    def save_record(
        self,
        *,
        run_id: int,
        dedupe_key: str,
        fields: dict,
        evidence: dict,
        source_type: str,
        official_source_url: str,
        application_url: str,
        discovered_via: str,
        confidence: float,
        score_components: list,
        lifecycle_status: str,
        verification_status: str,
    ) -> tuple[int, bool, list[dict]]:
        """Insert or update a record, snapshot it, and diff against the
        previous snapshot. Returns (scholarship_id, is_new, changes)."""
        now = _now()
        existing = self.get_by_key(dedupe_key)
        is_new = existing is None
        fields_json = json.dumps(fields, ensure_ascii=False)
        if is_new:
            cur = self.conn.execute(
                "INSERT INTO scholarships (dedupe_key, name, provider, source_type,"
                " official_source_url, application_url, discovered_via, fields_json,"
                " confidence, score_components, lifecycle_status, verification_status,"
                " first_seen_run, last_seen_run, last_verified_at, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    dedupe_key, fields.get("name", ""), fields.get("provider", ""),
                    source_type, official_source_url, application_url, discovered_via,
                    fields_json, confidence, json.dumps(score_components),
                    lifecycle_status, verification_status, run_id, run_id, now, now, now,
                ),
            )
            sid = int(cur.lastrowid)
            prev_fields = None
        else:
            sid = int(existing["id"])
            prev_row = self.conn.execute(
                "SELECT fields_json FROM snapshots WHERE scholarship_id=? "
                "ORDER BY run_id DESC, id DESC LIMIT 1",
                (sid,),
            ).fetchone()
            prev_fields = json.loads(prev_row["fields_json"]) if prev_row else None
            self.conn.execute(
                "UPDATE scholarships SET name=?, provider=?, source_type=?,"
                " official_source_url=?, application_url=?, fields_json=?,"
                " confidence=?, score_components=?, lifecycle_status=?,"
                " verification_status=?, last_seen_run=?, last_verified_at=?,"
                " updated_at=? WHERE id=?",
                (
                    fields.get("name", ""), fields.get("provider", ""), source_type,
                    official_source_url, application_url, fields_json, confidence,
                    json.dumps(score_components), lifecycle_status, verification_status,
                    run_id, now, now, sid,
                ),
            )

        self.conn.execute(
            "INSERT INTO snapshots (scholarship_id, run_id, fields_json, content_hash, captured_at)"
            " VALUES (?,?,?,?,?)",
            (sid, run_id, fields_json, content_hash(fields), now),
        )
        for field_name, snippet in evidence.items():
            self.conn.execute(
                "INSERT INTO field_evidence (scholarship_id, run_id, field, value, evidence, source_url)"
                " VALUES (?,?,?,?,?,?)",
                (sid, run_id, field_name, fields.get(field_name, ""), snippet, official_source_url),
            )

        changes: list[dict] = []
        if prev_fields is not None:
            for f in COMPARABLE_FIELDS + ["application_url"]:
                old = (prev_fields.get(f) if f != "application_url" else None)
                if f == "application_url":
                    old = existing["application_url"] if existing else None
                    new = application_url
                else:
                    new = fields.get(f)
                if (old or "") != (new or ""):
                    change = {
                        "field": f,
                        "old_value": old or "",
                        "new_value": new or "",
                        "source_url": official_source_url,
                        "evidence": evidence.get(f, "") if f != "application_url" else "",
                    }
                    changes.append(change)
                    self.conn.execute(
                        "INSERT INTO changes (scholarship_id, run_id, field, old_value,"
                        " new_value, detected_at, source_url, evidence) VALUES (?,?,?,?,?,?,?,?)",
                        (sid, run_id, f, change["old_value"], change["new_value"],
                         now, official_source_url, change["evidence"]),
                    )
        self.conn.commit()
        return sid, is_new, changes

    def mark_no_longer_verifiable(self, run_id: int, scholarship_id: int, reason: str) -> None:
        row = self.conn.execute(
            "SELECT * FROM scholarships WHERE id=?", (scholarship_id,)
        ).fetchone()
        if row is None or row["lifecycle_status"] == "NO_LONGER_VERIFIABLE":
            return
        self.conn.execute(
            "UPDATE scholarships SET lifecycle_status='NO_LONGER_VERIFIABLE', updated_at=? WHERE id=?",
            (_now(), scholarship_id),
        )
        self.conn.execute(
            "INSERT INTO changes (scholarship_id, run_id, field, old_value, new_value,"
            " detected_at, source_url, evidence) VALUES (?,?,?,?,?,?,?,?)",
            (scholarship_id, run_id, "lifecycle_status", row["lifecycle_status"],
             "NO_LONGER_VERIFIABLE", _now(), row["official_source_url"], reason),
        )
        self.conn.commit()

    # -- reporting ------------------------------------------------------------
    def stats(self) -> dict:
        q = lambda sql: self.conn.execute(sql).fetchone()[0]
        total = q("SELECT COUNT(*) FROM scholarships")
        verified = q("SELECT COUNT(*) FROM scholarships WHERE verification_status='VERIFIED'")
        high = q("SELECT COUNT(*) FROM scholarships WHERE confidence>=95")
        avg = self.conn.execute("SELECT AVG(confidence) FROM scholarships").fetchone()[0]
        return {
            "total": total,
            "verified": verified,
            "review_required": total - verified,
            "confidence_ge_95": high,
            "active": q("SELECT COUNT(*) FROM scholarships WHERE lifecycle_status='ACTIVE'"),
            "expiring_soon": q("SELECT COUNT(*) FROM scholarships WHERE lifecycle_status='EXPIRING_SOON'"),
            "expired": q("SELECT COUNT(*) FROM scholarships WHERE lifecycle_status='EXPIRED'"),
            "no_longer_verifiable": q("SELECT COUNT(*) FROM scholarships WHERE lifecycle_status='NO_LONGER_VERIFIABLE'"),
            "average_confidence": round(avg, 1) if avg else 0.0,
            "source_types": self.conn.execute(
                "SELECT COUNT(DISTINCT source_type) FROM scholarships"
            ).fetchone()[0],
            "changes_total": q("SELECT COUNT(*) FROM changes"),
            "runs": q("SELECT COUNT(*) FROM runs"),
        }

    def export_records(self) -> list[dict]:
        out = []
        for row in self.all_records():
            rec = dict(row)
            rec["fields"] = json.loads(rec.pop("fields_json") or "{}")
            rec["score_components"] = json.loads(rec.pop("score_components") or "[]")
            rec["evidence"] = [
                dict(r)
                for r in self.conn.execute(
                    "SELECT field, value, evidence, source_url FROM field_evidence"
                    " WHERE scholarship_id=? AND run_id=(SELECT MAX(run_id) FROM field_evidence WHERE scholarship_id=?)",
                    (row["id"], row["id"]),
                ).fetchall()
            ]
            rec["changes"] = [
                dict(r)
                for r in self.conn.execute(
                    "SELECT field, old_value, new_value, detected_at, source_url, evidence"
                    " FROM changes WHERE scholarship_id=? ORDER BY id",
                    (row["id"],),
                ).fetchall()
            ]
            out.append(rec)
        return out
