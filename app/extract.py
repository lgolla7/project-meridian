"""Build the knowledge database from the BOM, manifest, and drawing text.

The database is a pure function of dataset/. Review decisions live in a second
file so a rebuild cannot rewrite an accepted correction.
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from pathlib import Path

from pypdf import PdfReader

from app.catalog import (
    DRAWING_QUOTES,
    FILENAME_ALIASES,
    FILENAME_TITLES,
    LINKS,
    README_CLAIMS,
    RECONSTRUCTIONS,
    TEXT_ALIASES,
)
from app.config import BOM_CSV, DATA, DIAGRAMS, KNOWLEDGE_DB, MANIFEST, README
from app.textutil import quote_in_text

SCHEMA = """
CREATE TABLE bom_items (
    id TEXT PRIMARY KEY,
    source_row INTEGER,
    name TEXT,
    family TEXT,
    type TEXT,
    design_state TEXT,
    order_state TEXT,
    vv_state TEXT,
    notes TEXT,
    design_intent TEXT,
    material TEXT,
    product_name TEXT,
    supplier_order TEXT,
    interface_with TEXT,
    link TEXT,
    supplier TEXT,
    amount TEXT,
    cost TEXT,
    total_cost TEXT
);
CREATE TABLE drawings (
    id TEXT PRIMARY KEY,
    subsystem TEXT,
    role TEXT,
    distribution TEXT,
    pages INTEGER,
    source_path TEXT,
    file_path TEXT,
    title TEXT,
    title_origin TEXT,
    aliases TEXT,
    material_callout TEXT,
    weight_callout TEXT,
    extracted_note TEXT,
    char_count INTEGER,
    text TEXT,
    modification_notice TEXT
);
CREATE TABLE links (
    drawing_id TEXT,
    bom_id TEXT,
    relation TEXT,
    confidence TEXT,
    reason TEXT
);
CREATE TABLE claims (
    id TEXT PRIMARY KEY,
    statement TEXT,
    source TEXT,
    snippet TEXT
);
CREATE TABLE reconstructions (
    drawing_id TEXT PRIMARY KEY,
    title TEXT,
    shape TEXT,
    params_json TEXT,
    caveat TEXT
);
CREATE TABLE diagrams (
    id TEXT PRIMARY KEY,
    file_name TEXT,
    title TEXT
);
"""


def _clean(value: str | None) -> str:
    return " ".join((value or "").replace("\ufeff", "").split())


def _weight_callout(text: str) -> str:
    match = re.search(r"WEIGHT \[g\]:\s*(.+)", text)
    if not match:
        return ""
    value = match.group(1).split("UNLESS")[0].strip(" :")
    if not value or value.upper().startswith("UNLESS") or not re.search(r"\d", value):
        return ""
    return " ".join(value.split())


def _material_callout(text: str, drawing_id: str) -> str:
    """Prefer a short material phrase that is already quote-locked."""
    preferred = {
        "D-002": "2mm non-magnetic stainless",
        "D-004": "3 mm non-magnetic stainless",
        "D-005": "6061 Alloy",
        "D-006": "Non-magnetic stainless 3mm (or thicker)",
        "D-007": "Aluminium",
        "D-008": "2-3mm non-magnetic stainless",
        "D-010": "2mm non-magnetic stainless",
        "D-012": "Alu",
        "D-013": "Alu",
        "D-014": "Alu",
        "D-015": "silikone plade",
        "D-016": "Aluminium",
        "D-017": "Alu",
        "D-018": "7075-T6",
        "D-019": "1mm silicone pakning",
        "D-021": "Non-magnetic stainless",
        "D-024": "Aluminium",
        "D-025": "Aluminium",
        "D-026": "AISI 316",
        "D-027": "6063-T6",
        "D-028": "Aluminium",
        "D-029": "Aluminium",
    }
    callout = preferred.get(drawing_id, "")
    if callout and not quote_in_text(callout, text):
        raise SystemExit(f"{drawing_id} material callout {callout!r} is not in the sheet text")
    return callout


def _note(text: str) -> str:
    head = text.split("UNLESS OTHERWISE SPECIFIED")[0]
    return " ".join(head.split())[:700]


def _title_from_text(text: str, drawing_id: str) -> tuple[str, str]:
    if drawing_id in FILENAME_TITLES:
        return FILENAME_TITLES[drawing_id], "filename"
    quotes = DRAWING_QUOTES.get(drawing_id, [])
    # The first quote in the catalog is the title block name.
    if quotes:
        return quotes[0], "title-block"
    return drawing_id, "id"


def _aliases(drawing_id: str, title: str) -> str:
    found = []
    for item in TEXT_ALIASES.get(drawing_id, []) + FILENAME_ALIASES.get(drawing_id, []):
        if item not in found:
            found.append(item)
    if title and title not in found:
        found.append(title)
    return " | ".join(found)


def _require_quotes(drawing_id: str, text: str) -> None:
    if drawing_id in FILENAME_TITLES:
        if len(text.strip()) > 20:
            raise SystemExit(f"{drawing_id} was marked textless but extraction found text")
        return
    for quote in DRAWING_QUOTES.get(drawing_id, []):
        if not quote_in_text(quote, text):
            raise SystemExit(f"{drawing_id} is missing quote {quote!r}")


def _load_bom(conn: sqlite3.Connection) -> dict[str, str]:
    by_name: dict[str, str] = {}
    with BOM_CSV.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for index, row in enumerate(rows, start=1):
        item_id = f"B{index:03d}"
        name = _clean(row.get("Name"))
        if name in by_name:
            raise SystemExit(f"Duplicate BOM name {name}")
        by_name[name] = item_id
        conn.execute(
            """INSERT INTO bom_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                item_id,
                index,
                name,
                _clean(row.get("Part family")),
                _clean(row.get("Type")),
                _clean(row.get("Design")),
                _clean(row.get("Order")),
                _clean(row.get("V&V")),
                _clean(row.get("Notes")),
                _clean(row.get("Design Intend")),
                _clean(row.get("Material")),
                _clean(row.get("Product name")),
                _clean(row.get("Supplier Order")),
                _clean(row.get("Interface with")),
                _clean(row.get("Link")),
                _clean(row.get("Supplier")),
                _clean(row.get("Amount")),
                _clean(row.get("Cost")),
                _clean(row.get("Total cost")),
            ),
        )
    return by_name


def _load_drawings(conn: sqlite3.Connection) -> None:
    manifest = json.loads(MANIFEST.read_text())
    drawings = [asset for asset in manifest["assets"] if str(asset.get("path", "")).endswith(".pdf")]
    if len(drawings) != 30:
        raise SystemExit(f"Expected 30 drawings, found {len(drawings)}")
    for asset in drawings:
        drawing_id = asset["id"]
        path = Path(asset["path"])
        if not path.exists():
            path = Path("dataset") / "drawings" / f"{drawing_id}.pdf"
        reader = PdfReader(str(path))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        if len(reader.pages) != asset.get("pages"):
            raise SystemExit(f"{drawing_id} page count does not match the manifest")
        _require_quotes(drawing_id, text)
        title, origin = _title_from_text(text, drawing_id)
        notice = ""
        if asset.get("derivation"):
            notice = asset["derivation"].get("modification_notice", "")
        conn.execute(
            """INSERT INTO drawings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                drawing_id,
                asset.get("subsystem", ""),
                asset.get("role", ""),
                asset.get("distribution", ""),
                asset.get("pages", len(reader.pages)),
                asset.get("source_path", ""),
                str(path),
                title,
                origin,
                _aliases(drawing_id, title),
                _material_callout(text, drawing_id),
                _weight_callout(text),
                _note(text),
                len(text.strip()),
                text,
                notice,
            ),
        )


def _load_links(conn: sqlite3.Connection, names: dict[str, str]) -> None:
    for drawing_id, bom_name, relation, confidence, reason in LINKS:
        bom_id = names.get(bom_name)
        if not bom_id:
            raise SystemExit(f"Link target {bom_name!r} is not a BOM name")
        conn.execute(
            "INSERT INTO links VALUES (?,?,?,?,?)",
            (drawing_id, bom_id, relation, confidence, reason),
        )


def _load_claims(conn: sqlite3.Connection) -> None:
    readme = README.read_text()
    for claim in README_CLAIMS:
        if claim["snippet"] not in readme:
            raise SystemExit(f"Readme snippet missing for {claim['id']}")
        conn.execute(
            "INSERT INTO claims VALUES (?,?,?,?)",
            (claim["id"], claim["statement"], "OPENLPBF-README", claim["snippet"]),
        )


def _load_reconstructions(conn: sqlite3.Connection) -> None:
    for drawing_id, spec in RECONSTRUCTIONS.items():
        row = conn.execute("SELECT text FROM drawings WHERE id = ?", (drawing_id,)).fetchone()
        if row is None:
            raise SystemExit(f"Reconstruction {drawing_id} has no drawing")
        for quote in spec["quotes"]:
            if not quote_in_text(quote, row[0]):
                raise SystemExit(f"Reconstruction {drawing_id} uses missing quote {quote!r}")
        conn.execute(
            "INSERT INTO reconstructions VALUES (?,?,?,?,?)",
            (drawing_id, spec["title"], spec["shape"], json.dumps(spec["params"]), spec["caveat"]),
        )


def _load_diagrams(conn: sqlite3.Connection) -> None:
    manifest = json.loads(MANIFEST.read_text())
    for asset in manifest["assets"]:
        if asset.get("media_type") != "image/png":
            continue
        file_name = Path(asset["path"]).name
        if not (DIAGRAMS / file_name).exists():
            raise SystemExit(f"Missing diagram {file_name}")
        title = asset.get("source_path", file_name).split("/")[-1]
        conn.execute("INSERT INTO diagrams VALUES (?,?,?)", (asset["id"], file_name, title))


def build(db_path: Path = KNOWLEDGE_DB) -> Path:
    DATA.mkdir(exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        names = _load_bom(conn)
        _load_drawings(conn)
        _load_links(conn, names)
        _load_claims(conn)
        _load_reconstructions(conn)
        _load_diagrams(conn)
        conn.commit()
    finally:
        conn.close()
    return db_path


def main() -> None:
    path = build()
    conn = sqlite3.connect(path)
    bom = conn.execute("SELECT COUNT(*) FROM bom_items").fetchone()[0]
    drawings = conn.execute("SELECT COUNT(*) FROM drawings").fetchone()[0]
    silent = conn.execute("SELECT COUNT(*) FROM drawings WHERE char_count < 20").fetchone()[0]
    links = conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
    conn.close()
    print(f"Wrote {path} ({bom} BOM rows, {drawings} drawings, {silent} without text, {links} links)")


if __name__ == "__main__":
    main()
