"""Load the extracted database into memory for the answerer and the graph."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from app.catalog import SUBSYSTEM_FAMILIES
from app.config import KNOWLEDGE_DB
from app.textutil import normalize


@dataclass
class BomItem:
    id: str
    source_row: int
    name: str
    family: str
    type: str
    design_state: str
    order_state: str
    vv_state: str
    notes: str
    design_intent: str
    material: str
    product_name: str
    supplier_order: str
    interface_with: str
    link: str
    supplier: str
    amount: str
    cost: str
    total_cost: str

    def field(self, name: str) -> str:
        return getattr(self, name, "") or ""


@dataclass
class Drawing:
    id: str
    subsystem: str
    role: str
    distribution: str
    pages: int
    source_path: str
    file_path: str
    title: str
    title_origin: str
    aliases: str
    material_callout: str
    weight_callout: str
    extracted_note: str
    char_count: int
    text: str
    modification_notice: str

    @property
    def readable(self) -> bool:
        return self.char_count >= 20 and self.distribution == "clean"


@dataclass
class Link:
    drawing_id: str
    bom_id: str
    relation: str
    confidence: str
    reason: str


@dataclass
class Knowledge:
    boms: dict[str, BomItem]
    drawings: dict[str, Drawing]
    links: list[Link]
    claims: list[dict]
    reconstructions: dict[str, dict]
    diagrams: list[dict]
    by_name: dict[str, BomItem] = field(default_factory=dict)
    interfaces: list[tuple[str, str | None, str]] = field(default_factory=list)

    def links_for_bom(self, bom_id: str) -> list[Link]:
        return [link for link in self.links if link.bom_id == bom_id]

    def links_for_drawing(self, drawing_id: str) -> list[Link]:
        return [link for link in self.links if link.drawing_id == drawing_id]

    def partners(self, bom_id: str) -> list[tuple[BomItem | None, str]]:
        found: list[tuple[BomItem | None, str]] = []
        seen = set()
        for left, right, raw in self.interfaces:
            other_id = None
            if left == bom_id and right:
                other_id = right
            elif right == bom_id:
                other_id = left
            elif left == bom_id and not right:
                key = ("raw", raw)
                if key not in seen:
                    seen.add(key)
                    found.append((None, raw))
                continue
            if other_id and other_id not in seen:
                seen.add(other_id)
                found.append((self.boms[other_id], raw))
        return found

    def graph(self) -> dict:
        """Drawing subsystems, their BOM families, and the interfaces among them."""
        families = {name for names in SUBSYSTEM_FAMILIES.values() for name in names}
        nodes = []
        edges = []
        keep_bom = set()
        for item in self.boms.values():
            if item.family in families:
                keep_bom.add(item.id)
        for link in self.links:
            keep_bom.add(link.bom_id)
        for left, right, _raw in self.interfaces:
            if left in keep_bom and right:
                keep_bom.add(right)

        for name in SUBSYSTEM_FAMILIES:
            nodes.append({"id": f"sub:{name}", "label": name, "kind": "subsystem"})
        seen_families = set()
        for item in self.boms.values():
            if item.id not in keep_bom or item.family in seen_families:
                continue
            seen_families.add(item.family)
            nodes.append({"id": f"fam:{item.family}", "label": item.family, "kind": "family"})
        for subsystem, fams in SUBSYSTEM_FAMILIES.items():
            for fam in fams:
                edges.append({"source": f"sub:{subsystem}", "target": f"fam:{fam}", "kind": "maps-to"})

        materials = set()
        for item in self.boms.values():
            if item.id not in keep_bom:
                continue
            nodes.append({
                "id": item.id,
                "label": item.name,
                "kind": "bom",
                "family": item.family,
            })
            edges.append({"source": item.id, "target": f"fam:{item.family}", "kind": "in-family"})
            if item.material:
                for piece in [part.strip() for part in item.material.split(",") if part.strip()]:
                    mid = "mat:" + normalize(piece)
                    if mid not in materials:
                        materials.add(mid)
                        nodes.append({"id": mid, "label": piece, "kind": "material"})
                    edges.append({"source": item.id, "target": mid, "kind": "material"})

        for drawing in self.drawings.values():
            nodes.append({
                "id": drawing.id,
                "label": f"{drawing.id} {drawing.title}",
                "kind": "drawing",
                "distribution": drawing.distribution,
            })
            edges.append({
                "source": drawing.id,
                "target": f"sub:{drawing.subsystem}",
                "kind": "in-subsystem",
            })
        for link in self.links:
            if link.bom_id not in keep_bom:
                continue
            edges.append({
                "source": link.drawing_id,
                "target": link.bom_id,
                "kind": link.relation,
            })
        for left, right, _raw in self.interfaces:
            if right and left in keep_bom and right in keep_bom and left < right:
                edges.append({"source": left, "target": right, "kind": "interface"})
        return {
            "nodes": nodes,
            "edges": edges,
            "note": "Electrical, sensor-gantry, support, and raw-material rows are omitted until a drawing or an interface connects them.",
        }


def _bom_from_row(row: sqlite3.Row) -> BomItem:
    return BomItem(**{key: row[key] for key in BomItem.__dataclass_fields__})


def _drawing_from_row(row: sqlite3.Row) -> Drawing:
    return Drawing(**{key: row[key] for key in Drawing.__dataclass_fields__})


def load(db_path=KNOWLEDGE_DB) -> Knowledge:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        boms = {
            row["id"]: _bom_from_row(row)
            for row in conn.execute("SELECT * FROM bom_items")
        }
        drawings = {
            row["id"]: _drawing_from_row(row)
            for row in conn.execute("SELECT * FROM drawings")
        }
        links = [
            Link(**dict(row))
            for row in conn.execute("SELECT * FROM links")
        ]
        claims = [dict(row) for row in conn.execute("SELECT * FROM claims")]
        reconstructions = {}
        for row in conn.execute("SELECT * FROM reconstructions"):
            reconstructions[row["drawing_id"]] = {
                "drawing_id": row["drawing_id"],
                "title": row["title"],
                "shape": row["shape"],
                "params": json.loads(row["params_json"]),
                "caveat": row["caveat"],
                "label": "Reconstruction from 2D evidence, not native CAD",
                "units": "mm",
            }
        diagrams = [dict(row) for row in conn.execute("SELECT * FROM diagrams")]
    finally:
        conn.close()

    knowledge = Knowledge(
        boms=boms,
        drawings=drawings,
        links=links,
        claims=claims,
        reconstructions=reconstructions,
        diagrams=diagrams,
    )
    knowledge.by_name = {normalize(item.name): item for item in boms.values()}
    for item in boms.values():
        for piece in [part.strip() for part in item.interface_with.split(",") if part.strip()]:
            other = knowledge.by_name.get(normalize(piece))
            knowledge.interfaces.append((item.id, other.id if other else None, piece))
    return knowledge


def catalog_payload(knowledge: Knowledge) -> dict:
    drawings = []
    for drawing in knowledge.drawings.values():
        bom_links = []
        for link in knowledge.links_for_drawing(drawing.id):
            bom = knowledge.boms[link.bom_id]
            bom_links.append({
                "bom_id": bom.id,
                "name": bom.name,
                "relation": link.relation,
                "confidence": link.confidence,
            })
        drawings.append({
            "id": drawing.id,
            "title": drawing.title,
            "title_origin": drawing.title_origin,
            "subsystem": drawing.subsystem,
            "distribution": drawing.distribution,
            "readable": drawing.readable,
            "has_3d": drawing.id in knowledge.reconstructions,
            "material_callout": drawing.material_callout,
            "links": bom_links,
        })
    return {
        "drawings": drawings,
        "reconstructions": list(knowledge.reconstructions.keys()),
        "subsystems": list(SUBSYSTEM_FAMILIES),
    }
