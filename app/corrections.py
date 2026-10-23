"""Human review ledger.

Knowledge can be rebuilt from the files. This database is the only place a
person's accept or reject is stored, and rows are never deleted.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone

from app.config import CORRECTIONS_DB, DATA
from app.knowledge import BomItem, Knowledge

SCHEMA = """
CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    target_id TEXT NOT NULL,
    target_label TEXT NOT NULL,
    field TEXT NOT NULL,
    original_value TEXT NOT NULL,
    proposed_value TEXT NOT NULL,
    rationale TEXT NOT NULL,
    check_summary TEXT NOT NULL,
    check_detail TEXT NOT NULL,
    resolved_at TEXT,
    reviewer_note TEXT
);
"""

FIELDS = {
    "material": "material",
    "supplier": "supplier",
    "cost": "cost",
    "notes": "notes",
    "v&v": "vv_state",
    "vv": "vv_state",
    "validation": "vv_state",
    "order": "order_state",
    "design intent": "design_intent",
}

PATTERNS = [
    re.compile(
        r"propose(?:\s+a)?\s+correction\s*:\s*(?P<target>.+?)\s+"
        r"(?P<field>material|supplier|cost|notes|v&v|vv|validation|order|design intent)\s+"
        r"(?:should be|to|=)\s+(?P<value>.+?)\s*\.?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"correct(?:\s+the)?\s+"
        r"(?P<field>material|supplier|cost|notes|v&v|vv|validation|order|design intent)\s+"
        r"of\s+(?P<target>.+?)\s+to\s+(?P<value>.+?)\s*\.?$",
        re.IGNORECASE,
    ),
]


def connect(path=CORRECTIONS_DB) -> sqlite3.Connection:
    DATA.mkdir(exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_proposal(message: str) -> dict | None:
    text = " ".join(message.strip().split())
    for pattern in PATTERNS:
        match = pattern.search(text)
        if match:
            return {
                "target": match.group("target").strip(" :"),
                "field": FIELDS[match.group("field").lower()],
                "field_words": match.group("field").lower(),
                "value": match.group("value").strip(" ."),
            }
    return None


def assess(knowledge: Knowledge, bom: BomItem, field: str, proposed: str) -> tuple[str, str]:
    """Freeze a check the reviewer can read. Acceptance does not run this again."""
    original = bom.field(field) or "(blank)"
    lines = [
        f"BOM {bom.id} {bom.name} records {field} as {original!r}.",
        f"Proposed value: {proposed!r}.",
    ]
    support = []
    missing = []
    saw_sheet = False
    tokens = [tok for tok in re.split(r"[^A-Za-z0-9.+-]+", proposed) if len(tok) >= 3]
    for link in knowledge.links_for_bom(bom.id):
        if link.relation == "rejected":
            continue
        drawing = knowledge.drawings[link.drawing_id]
        if not drawing.text.strip():
            lines.append(
                f"{drawing.id} ({link.relation}) has no extractable text, so the sheet cannot confirm this."
            )
            continue
        saw_sheet = True
        if field != "material":
            lines.append(
                f"{drawing.id} is linked, but this check only searches sheet text for a material proposal. "
                f"{field} still needs a human to compare the cells."
            )
            continue
        hits = []
        lowered = drawing.text.lower()
        for tok in tokens:
            forms = {tok.lower(), tok.lower().replace("aluminum", "aluminium")}
            if any(form in lowered for form in forms):
                hits.append(tok)
        if hits:
            support.append(
                f"{drawing.id} ({link.relation}, {link.confidence}) contains {', '.join(hits)}. "
                f"Extracted callout: {drawing.material_callout or '(none)'}."
            )
        else:
            missing.append(
                f"{drawing.id} does not contain those words. Extracted callout: "
                f"{drawing.material_callout or '(none)'}."
            )
    if field == "material" and support:
        summary = "Drawing text supports at least part of the proposed material. The original BOM cell is kept either way."
    elif field == "material" and missing and not support:
        summary = "No linked sheet contains the proposed material words. A reviewer may still accept or reject it."
    elif not saw_sheet:
        summary = "No readable linked drawing can confirm this. The decision is entirely the reviewer's."
    else:
        summary = "The proposal is stored with the original value. Automatic checking did not verify this field against the sheet."
    detail = "\n".join(lines + support + missing)
    return summary, detail


def public(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def list_all(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM corrections ORDER BY id DESC").fetchall()
    return [public(row) for row in rows]


def effective(conn: sqlite3.Connection, bom: BomItem, field: str) -> tuple[str, dict | None]:
    row = conn.execute(
        """
        SELECT * FROM corrections
        WHERE target_id = ? AND field = ? AND status = 'accepted'
        ORDER BY resolved_at DESC, id DESC
        LIMIT 1
        """,
        (bom.id, field),
    ).fetchone()
    original = bom.field(field)
    if row is None:
        return original, None
    if row["target_label"] != bom.name:
        return original, None
    return row["proposed_value"], public(row)


def propose(conn: sqlite3.Connection, knowledge: Knowledge, bom: BomItem, field: str, value: str, rationale: str) -> dict:
    existing = conn.execute(
        """
        SELECT * FROM corrections
        WHERE target_id = ? AND field = ? AND proposed_value = ? AND status = 'pending'
        ORDER BY id DESC LIMIT 1
        """,
        (bom.id, field, value),
    ).fetchone()
    if existing:
        return public(existing)
    summary, detail = assess(knowledge, bom, field, value)
    cur = conn.execute(
        """
        INSERT INTO corrections (
            created_at, status, target_id, target_label, field, original_value,
            proposed_value, rationale, check_summary, check_detail
        ) VALUES (?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (now(), bom.id, bom.name, field, bom.field(field), value, rationale, summary, detail),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM corrections WHERE id = ?", (cur.lastrowid,)).fetchone()
    return public(row)


def resolve(conn: sqlite3.Connection, correction_id: int, status: str, note: str) -> dict | None:
    row = conn.execute("SELECT * FROM corrections WHERE id = ?", (correction_id,)).fetchone()
    if row is None:
        return None
    if row["status"] != "pending":
        return public(row)
    conn.execute(
        """
        UPDATE corrections
        SET status = ?, resolved_at = ?, reviewer_note = ?
        WHERE id = ?
        """,
        (status, now(), note.strip(), correction_id),
    )
    conn.commit()
    return public(conn.execute("SELECT * FROM corrections WHERE id = ?", (correction_id,)).fetchone())
