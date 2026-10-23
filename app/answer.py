"""Answer from extracted rows and accepted corrections, never from a raw PDF dump."""

from __future__ import annotations

import re
import sqlite3

from app.catalog import SUBSYSTEM_FAMILIES
from app.corrections import effective, list_all, parse_proposal, propose
from app.knowledge import BomItem, Drawing, Knowledge, Link
from app.llm import narrate
from app.textutil import fold, normalize, snippet, tokens

CAVEAT = (
    "Supplier, order number, and cost are the pinned BOM snapshot. "
    "They are not a current price, a stock check, or an endorsement."
)

GENERIC = {
    "plate", "steel", "door", "frame", "ring", "base", "wall", "shaft", "block",
    "motor", "powder", "laser", "window", "side", "head", "arm", "box", "flow",
    "gas", "axis", "build", "mount", "bracket", "sensor", "driver", "screw",
    "nut", "sheet", "tube", "valve", "filter",
}

EXAMPLES = [
    "How is OpenLPBF v2 organized?",
    "What is the material of the window frame, and does the drawing agree?",
    "Show the dispenser shaft and its 3D reconstruction.",
    "Is the powder motor plate the same part as the build-plate motor plate?",
    "Which parts are recorded as stainless steel?",
    "What interfaces with the front door?",
    "What supplier and cost are recorded for the laser safety window?",
    "What are the hole sizes on the powder canister drawing?",
    "What is the laser M2?",
    "Where do drawing materials and BOM materials disagree?",
    "Propose a correction: Window Frame material should be 6061 aluminium",
]


class Draft:
    def __init__(self, question: str, intent: str):
        self.question = question
        self.intent = intent
        self.blocks: list[dict] = []
        self.citations: list[dict] = []
        self.visuals: list[dict] = []
        self.abstained = False
        self.correction = None
        self._cites: set[tuple] = set()

    def p(self, text: str) -> None:
        self.blocks.append({"type": "p", "text": text})

    def warn(self, text: str) -> None:
        self.blocks.append({"type": "warn", "text": text})

    def fact(self, label: str, value: str) -> None:
        self.blocks.append({"type": "fact", "label": label, "value": value or "(blank)"})

    def cite(self, source: str, item_id: str, label: str, text: str, needle: str = "") -> None:
        key = (source, item_id, label)
        if key in self._cites:
            return
        self._cites.add(key)
        self.citations.append({
            "source": source,
            "id": item_id,
            "label": label,
            "snippet": snippet(text, needle),
        })

    def attach_drawing(self, drawing: Drawing, knowledge: Knowledge) -> None:
        if any(item["id"] == drawing.id for item in self.visuals):
            return
        self.visuals.append({
            "kind": "drawing",
            "id": drawing.id,
            "title": drawing.title,
            "has_3d": drawing.id in knowledge.reconstructions,
            "distribution": drawing.distribution,
        })

    def attach_diagram(self, diagram: dict) -> None:
        self.visuals.append({
            "kind": "diagram",
            "id": diagram["id"],
            "title": diagram["title"],
            "has_3d": False,
            "distribution": "diagram",
        })

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "intent": self.intent,
            "abstained": self.abstained,
            "blocks": self.blocks,
            "citations": self.citations[:8],
            "visuals": self.visuals[:4],
            "correction": self.correction,
        }


class Cluster:
    def __init__(self):
        self.boms: list[BomItem] = []
        self.drawings: list[Drawing] = []
        self.links: list[Link] = []

    def specificity(self, query_norm: str) -> int:
        best = 0
        for drawing in self.drawings:
            for alias in drawing.aliases.split("|"):
                phrase = normalize(alias)
                if phrase and re.search(rf"(^| ){re.escape(phrase)}( |$)", query_norm):
                    best = max(best, len(phrase))
            if drawing.id.lower() in query_norm:
                best = max(best, 12)
        for bom in self.boms:
            phrase = normalize(bom.name)
            if phrase and re.search(rf"(^| ){re.escape(phrase)}( |$)", query_norm):
                best = max(best, len(phrase))
        return best


def _phrase_in(label: str, query_norm: str) -> bool:
    """Match a whole name, but not when the next word shows it was only a modifier.

    "build-plate motor plate" contains the words "build plate", yet the next
    word is "motor", so that hit is the build-plate family rather than the
    Build Plate part.
    """
    phrase = normalize(label)
    words = phrase.split()
    if not words or len(phrase) < 4:
        return False
    if len(words) == 1 and words[0] in GENERIC:
        return False
    for match in re.finditer(rf"(^| ){re.escape(phrase)}( |$)", query_norm):
        rest = query_norm[match.end():].strip()
        nxt = rest.split(" ")[0] if rest else ""
        if nxt and nxt in GENERIC:
            continue
        return True
    return False


def find_clusters(text: str, knowledge: Knowledge) -> list[Cluster]:
    query_norm = normalize(text)
    bom_hits: list[BomItem] = []
    drawing_hits: list[Drawing] = []
    for bom in knowledge.boms.values():
        if _phrase_in(bom.name, query_norm):
            bom_hits.append(bom)
    for drawing in knowledge.drawings.values():
        labels = [drawing.title, drawing.id, *drawing.aliases.split("|")]
        if drawing.id.lower() in text.lower() or any(_phrase_in(label, query_norm) for label in labels):
            drawing_hits.append(drawing)

    used_drawings: set[str] = set()
    clusters: list[Cluster] = []
    for bom in bom_hits:
        cluster = Cluster()
        cluster.boms.append(bom)
        for link in knowledge.links_for_bom(bom.id):
            cluster.links.append(link)
            if link.relation == "rejected":
                continue
            drawing = knowledge.drawings[link.drawing_id]
            if drawing not in cluster.drawings:
                cluster.drawings.append(drawing)
            if link.relation == "depicts":
                used_drawings.add(drawing.id)
        clusters.append(cluster)

    for drawing in drawing_hits:
        if drawing.id in used_drawings:
            continue
        cluster = Cluster()
        cluster.drawings.append(drawing)
        for link in knowledge.links_for_drawing(drawing.id):
            cluster.links.append(link)
            if link.relation == "depicts" and knowledge.boms[link.bom_id] not in cluster.boms:
                cluster.boms.append(knowledge.boms[link.bom_id])
        clusters.append(cluster)
        used_drawings.add(drawing.id)
    clusters.sort(key=lambda item: item.specificity(query_norm), reverse=True)
    return clusters


def _buckets(text: str) -> set[str]:
    found: set[str] = set()
    for piece in re.split(r"[,;/]| and | og ", text or ""):
        norm = fold(piece)
        if any(key in norm for key in ("stainless", "rustfri", "aisi 316", "aisi316")):
            found.add("stainless")
        if re.search(r"aluminium|aluminum|(^|[^a-z])alu([^a-z]|$)|6061|6063|7075|en-aw|en aw", norm):
            found.add("aluminium")
        if "silicone" in norm or "silikone" in norm or "silicon rubber" in norm:
            found.add("silicone")
        if "polymer" in norm:
            found.add("polymer")
        if "elastomer" in norm or "rubber" in norm:
            found.add("elastomer")
        if re.search(r"(^|[^a-z])steel", norm) and "stainless" not in norm:
            found.add("steel")
        if "ceramic" in norm:
            found.add("ceramic")
    return found


def _alloys(text: str) -> set[str]:
    norm = fold(text)
    return {token for token in ("6061", "6063", "7075", "316", "5005", "3.3315") if token in norm}


def _facets(text: str) -> set[str]:
    facets = set()
    if re.search(r"material|alloy|stainless|aluminium|aluminum|silicone", text, re.I):
        facets.add("material")
    if re.search(r"supplier|cost|price|dkk|order number|procure|who (made|supplied)", text, re.I):
        facets.add("procurement")
    if re.search(r"who could|who else|potential supplier|alternate supplier|could make|could supply", text, re.I):
        facets.add("capability")
    if re.search(r"interface|connect|mates|attached to|what touches", text, re.I):
        facets.add("interface")
    if re.search(r"dimension|hole|thickness|diameter|size|reconstruct|3d|orbit|geometry", text, re.I):
        facets.add("geometry")
    if re.search(r"validat|v&v|state|status|design intent|notes", text, re.I):
        facets.add("state")
    if re.search(r"disagree|conflict|contradict|agree|uncertain|same part", text, re.I):
        facets.add("compare")
    return facets


def _blank(value: str) -> str:
    return value if value else "(blank)"


def _cost_sentence(item: BomItem) -> str:
    if not item.cost:
        return "No unit cost is recorded. A blank is not a price of zero."
    compact = item.cost.replace(" ", "")
    if compact in {"DKK0.00", "DKK0", "0"}:
        return (
            f"The snapshot records unit cost {item.cost} and total {item.total_cost or '(blank)'}. "
            "On custom rows that usually means no purchase price was entered."
        )
    return (
        f"Recorded unit cost {item.cost}, amount {_blank(item.amount)}, "
        f"recorded total {_blank(item.total_cost)}."
    )


def _capability(bom: BomItem, drawings: list[Drawing]) -> str:
    blob = " ".join(
        [bom.material, bom.type, bom.design_intent, bom.notes]
        + [f"{item.material_callout} {item.extracted_note}" for item in drawings]
    )
    kinds = _buckets(blob)
    folded = fold(blob)
    if bom.type == "Standard" and bom.supplier:
        return (
            f"The only named supplier in evidence is {bom.supplier}. "
            "This app does not search live catalogs, so it will not name another company."
        )
    if "stainless" in kinds and any(word in folded for word in ("sheet", "weld", "plate", "wall", "mm")):
        return (
            "A laser-cutting sheet-metal shop that cuts non-magnetic stainless matches the sheet thickness "
            "and weld-nut notes. No shop is named in the corpus. This is a process match, not a quote."
        )
    if "aluminium" in kinds and any(word in folded for word in ("shaft", "cylinder", "turned", "bore")):
        return (
            "A turning shop matches a round aluminium part. No shop is named in the corpus. "
            "This is a process match, not availability."
        )
    if bom.type == "Custom" and "aluminium" in kinds:
        return (
            "A CNC milling shop matches a custom aluminium part. No shop is named in the corpus. "
            "This is a process match, not a quote."
        )
    if bom.supplier:
        return f"The recorded supplier is {bom.supplier}. Nothing else in the files names a maker."
    return "No supplier is recorded, and the files do not name an outside maker."


def _cite_bom(draft: Draft, bom: BomItem, label: str, needle: str = "") -> None:
    text = (
        f"Name: {bom.name}. Family: {bom.family}. Type: {bom.type}. "
        f"Material: {_blank(bom.material)}. Supplier: {_blank(bom.supplier)}. "
        f"Order: {_blank(bom.supplier_order)}. Cost: {_blank(bom.cost)}. "
        f"Interface with: {_blank(bom.interface_with)}. Notes: {_blank(bom.notes)}. "
        f"Design intent: {_blank(bom.design_intent)}."
    )
    draft.cite("bom", bom.id, f"{label}: {bom.name}", text, needle or bom.name)


def _cite_drawing(draft: Draft, drawing: Drawing) -> None:
    if drawing.text.strip():
        needle = drawing.material_callout or drawing.title
        draft.cite("drawing", drawing.id, f"{drawing.id} {drawing.title}", drawing.text, needle)
    else:
        notice = drawing.modification_notice or "No extractable text."
        draft.cite("drawing", drawing.id, f"{drawing.id} {drawing.title}", notice, "")


def _material_section(draft: Draft, knowledge: Knowledge, conn: sqlite3.Connection, bom: BomItem, drawings: list[Drawing]) -> None:
    shown, correction = effective(conn, bom, "material")
    if correction:
        draft.fact("Material used in answers", shown)
        draft.fact("Original BOM material", _blank(bom.material))
        draft.cite(
            "correction",
            str(correction["id"]),
            f"Accepted correction #{correction['id']}",
            correction["check_detail"],
            "",
        )
        draft.p(
            f"Accepted correction #{correction['id']} replaced the material used in answers. "
            "The BOM cell itself is unchanged."
        )
    else:
        draft.fact("BOM material", _blank(bom.material))
    _cite_bom(draft, bom, "BOM material", bom.material or bom.name)
    bom_sets = _buckets(shown)
    for drawing in drawings:
        if not any(link.drawing_id == drawing.id and link.relation == "depicts" for link in knowledge.links_for_bom(bom.id)):
            continue
        draft.attach_drawing(drawing, knowledge)
        _cite_drawing(draft, drawing)
        if not drawing.readable:
            draft.warn(
                f"{drawing.id} is {drawing.distribution} and has no readable text, so its material cannot be checked against the BOM."
            )
            continue
        callout = drawing.material_callout or "(no material callout extracted)"
        draft.fact(f"{drawing.id} material callout", callout)
        if drawing.weight_callout:
            draft.fact(f"{drawing.id} title-block weight line", drawing.weight_callout)
        draw_sets = _buckets(drawing.material_callout + " " + drawing.weight_callout + " " + drawing.extracted_note)
        if bom_sets and draw_sets and bom_sets.isdisjoint(draw_sets):
            draft.warn(
                f"Material families disagree: BOM {sorted(bom_sets)} versus drawing {sorted(draw_sets)}."
            )
        elif _alloys(drawing.material_callout + " " + drawing.weight_callout) - _alloys(shown):
            extra = ", ".join(sorted(_alloys(drawing.weight_callout + " " + drawing.material_callout) - _alloys(shown)))
            draft.warn(
                f"The drawing names alloy {extra}, which the BOM material cell does not. "
                "That is a more specific callout, not a second metal family, unless a correction is accepted."
            )
        elif bom_sets and draw_sets:
            draft.p(f"{drawing.id} and the BOM agree on {', '.join(sorted(bom_sets & draw_sets))}.")
        if "alu" in fold(drawing.extracted_note) and "stainless" in draw_sets:
            draft.warn(f"{drawing.id} also mentions both stainless and aluminium in the sheet note. Both are reported; neither is dropped.")


def _geometry_section(draft: Draft, knowledge: Knowledge, drawings: list[Drawing]) -> None:
    any_solid = False
    for drawing in drawings:
        draft.attach_drawing(drawing, knowledge)
        recon = knowledge.reconstructions.get(drawing.id)
        if recon:
            any_solid = True
            draft.p(f"{drawing.id} has an orbitable reconstruction: {recon['title']}. {recon['label']}.")
            draft.p(recon["caveat"])
            draft.cite("drawing", drawing.id, f"{drawing.id} reconstruction callouts", drawing.text, recon["title"])
        elif not drawing.readable:
            draft.abstained = True
            draft.warn(
                f"Hole sizes and other dimensions on {drawing.id} are not answered. "
                "The sheet is a degraded scan with no extractable text, and there is no reconstruction."
            )
            if drawing.modification_notice:
                draft.cite("drawing", drawing.id, f"{drawing.id} modification notice", drawing.modification_notice)
        else:
            calls = re.findall(r"\d+\s*x\s*[\d,.]+\s*(?:THRU[A-Z ]*)?", drawing.extracted_note, re.I)
            if calls:
                draft.p(
                    "These callouts were copied from the extracted note, not from a checked geometric parse: "
                    + "; ".join(calls[:8])
                    + "."
                )
                draft.cite("drawing", drawing.id, f"{drawing.id} extracted note", drawing.extracted_note)
            else:
                draft.p(f"{drawing.id} has readable text, but this system does not turn that sheet into a full dimension table.")
    if not any_solid:
        names = ", ".join(f"{item} ({knowledge.reconstructions[item]['title']})" for item in knowledge.reconstructions)
        draft.p(f"Orbitable reconstructions exist only for {names}.")


def _describe_bom(draft: Draft, knowledge: Knowledge, conn: sqlite3.Connection, bom: BomItem, drawings: list[Drawing], facets: set[str]) -> None:
    focused = bool(facets)
    draft.p(f"{bom.name} is a {bom.type or 'untyped'} {bom.family} row, BOM {bom.id}, source row {bom.source_row}.")
    linked = [knowledge.drawings[link.drawing_id] for link in knowledge.links_for_bom(bom.id) if link.relation == "depicts"]
    for drawing in linked:
        origin = "title block" if drawing.title_origin == "title-block" else drawing.title_origin
        draft.p(f"Linked drawing {drawing.id} ({drawing.title}, title from {origin}), {drawing.distribution}, subsystem {drawing.subsystem}.")
        others = [
            knowledge.boms[link.bom_id].name
            for link in knowledge.links_for_drawing(drawing.id)
            if link.relation == "depicts" and link.bom_id != bom.id
        ]
        if others:
            draft.p(f"{drawing.id} is also linked to {', '.join(others)}, because one sheet covers more than one BOM row.")
        draft.attach_drawing(drawing, knowledge)
        _cite_drawing(draft, drawing)
    if not focused or "material" in facets or "compare" in facets:
        _material_section(draft, knowledge, conn, bom, linked or drawings)
    if not focused or "procurement" in facets or "capability" in facets:
        draft.fact("Recorded supplier", _blank(bom.supplier))
        draft.fact("Recorded order number", _blank(bom.supplier_order))
        draft.p(_cost_sentence(bom))
        draft.warn(CAVEAT)
        _cite_bom(draft, bom, "BOM procurement", bom.supplier or bom.cost or bom.name)
        if bom.supplier == "DTU" and bom.type == "Custom":
            draft.p("DTU here is the project that designed the custom part, not a catalog vendor.")
    if "capability" in facets:
        draft.p(_capability(bom, linked))
    if not focused or "interface" in facets:
        partners = knowledge.partners(bom.id)
        if not partners and not bom.interface_with:
            draft.p("No interface text is recorded on this row, and no other row names it.")
        else:
            names = []
            for other, raw in partners:
                names.append(other.name if other else f"{raw} (no matching BOM row)")
            draft.p("Interfaces, read in both directions: " + ", ".join(names) + ".")
            draft.cite("bom", bom.id, f"Interfaces for {bom.name}", bom.interface_with or ", ".join(names), "")
    if not focused or "state" in facets:
        draft.fact("Design", _blank(bom.design_state))
        draft.fact("Order state", _blank(bom.order_state))
        draft.fact("V&V", _blank(bom.vv_state))
        if bom.notes:
            draft.fact("BOM notes", bom.notes)
        if bom.design_intent:
            draft.fact("Design intent", bom.design_intent)
        _cite_bom(draft, bom, "BOM state", bom.notes or bom.design_intent or bom.name)
    if "geometry" in facets:
        _geometry_section(draft, knowledge, linked or drawings)
    elif any(item.id in knowledge.reconstructions for item in (linked or drawings)):
        _geometry_section(draft, knowledge, [item for item in (linked or drawings) if item.id in knowledge.reconstructions])


def _describe_drawing(draft: Draft, knowledge: Knowledge, drawing: Drawing, facets: set[str]) -> None:
    origin = "filename, because the sheet has no extractable text" if drawing.title_origin == "filename" else drawing.title_origin
    draft.p(f"{drawing.id} is {drawing.title}. The title comes from the {origin}. Subsystem {drawing.subsystem}. Distribution {drawing.distribution}.")
    draft.attach_drawing(drawing, knowledge)
    _cite_drawing(draft, drawing)
    if drawing.material_callout:
        draft.fact("Material callout", drawing.material_callout)
    if drawing.weight_callout:
        draft.fact("Title-block weight line", drawing.weight_callout)
    depicts = [link for link in knowledge.links_for_drawing(drawing.id) if link.relation == "depicts"]
    if not depicts:
        draft.warn("No BOM row is settled for this sheet. Facts from similarly named rows are not copied in.")
    for link in knowledge.links_for_drawing(drawing.id):
        other = knowledge.boms[link.bom_id]
        if link.relation == "rejected":
            draft.warn(f"Not the same part as {other.name} ({other.id}). {link.reason}")
        elif link.relation == "candidate":
            draft.p(f"Possible BOM row {other.name} ({other.id}), not settled. {link.reason}")
    if "geometry" in facets or drawing.id in knowledge.reconstructions:
        _geometry_section(draft, knowledge, [drawing])
    if not drawing.readable and "geometry" not in facets:
        draft.warn(drawing.modification_notice or "This degraded scan has no extractable text. Dimensions and title-block fields are not read from it.")


def _answer_cluster(draft: Draft, knowledge: Knowledge, conn: sqlite3.Connection, cluster: Cluster, facets: set[str]) -> None:
    if cluster.boms:
        for bom in cluster.boms:
            _describe_bom(draft, knowledge, conn, bom, cluster.drawings, facets)
            for link in knowledge.links_for_bom(bom.id):
                drawing = knowledge.drawings[link.drawing_id]
                if link.relation == "rejected":
                    draft.warn(f"{drawing.id} ({drawing.title}) is not merged into {bom.name}. {link.reason}")
                elif link.relation == "candidate":
                    draft.p(f"Candidate sheet {drawing.id} ({drawing.title}), not settled. {link.reason}")
                    draft.attach_drawing(drawing, knowledge)
                    _cite_drawing(draft, drawing)
        return
    for drawing in cluster.drawings:
        _describe_drawing(draft, knowledge, drawing, facets)


def _materials(draft: Draft, knowledge: Knowledge, conn: sqlite3.Connection, text: str) -> None:
    asked = None
    for label, keys in (
        ("stainless", ("stainless", "rustfri")),
        ("aluminium", ("aluminium", "aluminum")),
        ("silicone", ("silicone", "silikone")),
        ("polymer", ("polymer",)),
        ("steel", ("steel",)),
    ):
        if any(key in fold(text) for key in keys):
            asked = label
            break
    if asked is None:
        asked = "stainless"
    groups: dict[str, list[str]] = {}
    for bom in knowledge.boms.values():
        shown, _correction = effective(conn, bom, "material")
        if asked in _buckets(shown):
            groups.setdefault(bom.family or "Unspecified", []).append(f"{bom.name} [{shown}]")
    draft.p(
        f"Parts whose recorded material cell, after any accepted correction, falls in the {asked} group. "
        "A blank cell is omitted rather than treated as this material."
    )
    if not groups:
        draft.p("No BOM row records that material.")
    for family in sorted(groups):
        names = groups[family]
        draft.p(f"{family} ({len(names)}): " + "; ".join(names[:12]) + ("…" if len(names) > 12 else ""))
    drawing_hits = []
    for drawing in knowledge.drawings.values():
        if asked in _buckets(drawing.material_callout):
            drawing_hits.append(f"{drawing.id} {drawing.title} [{drawing.material_callout}]")
    if drawing_hits:
        draft.p("Drawing callouts in the same group, kept separate from the BOM: " + "; ".join(drawing_hits) + ".")
    draft.cite("bom", "material-column", "BOM Material column", "Material values are copied from the pinned BOM snapshot.", "")


def _overview(draft: Draft, knowledge: Knowledge) -> None:
    draft.p("OpenLPBF v2 in this corpus is one research metal laser powder-bed-fusion machine, described by 30 drawings and 192 BOM rows.")
    for claim in knowledge.claims:
        draft.p(claim["statement"])
        draft.cite("readme", claim["id"], "Upstream readme", claim["snippet"], "")
    for diagram in knowledge.diagrams:
        if diagram["file_name"] == "SystemLevels.png":
            draft.attach_diagram(diagram)
            draft.cite("diagram", diagram["id"], diagram["title"], "System level diagram shipped with the corpus.", "")
    counts = []
    for subsystem, families in SUBSYSTEM_FAMILIES.items():
        sheets = [item for item in knowledge.drawings.values() if item.subsystem == subsystem]
        silent = sum(1 for item in sheets if not item.readable)
        bom_count = sum(1 for item in knowledge.boms.values() if item.family in families)
        counts.append(f"{subsystem}: {len(sheets)} drawings ({silent} unreadable), BOM family {', '.join(families)} has {bom_count} rows.")
    draft.p(" ".join(counts))
    draft.p(
        "Drawing subsystems and BOM families do not share one vocabulary: Optical maps to Optics, and Z-axis maps to Build-plate. "
        "Electric, SensorGantry, Support, and Raw Materials have BOM rows and no sheet in this 30-drawing set."
    )
    names = ", ".join(f"{key} {value['title']}" for key, value in knowledge.reconstructions.items())
    draft.p(f"Orbitable 3D reconstructions, labeled as reconstructions rather than CAD, exist for {names}.")


def _conflicts(draft: Draft, knowledge: Knowledge, conn: sqlite3.Connection) -> None:
    draft.p("Comparisons use only rows with a depicts or candidate link. Rejected links are listed on their own so a shared name is not treated as agreement.")
    found = False
    for link in knowledge.links:
        if link.relation == "rejected":
            bom = knowledge.boms[link.bom_id]
            drawing = knowledge.drawings[link.drawing_id]
            draft.warn(f"{drawing.id} rejected as {bom.name}. {link.reason}")
            draft.attach_drawing(drawing, knowledge)
            found = True
            continue
        drawing = knowledge.drawings[link.drawing_id]
        bom = knowledge.boms[link.bom_id]
        if not drawing.readable:
            draft.p(f"{drawing.id} linked to {bom.name} cannot be checked: the sheet has no extractable text.")
            continue
        shown, _correction = effective(conn, bom, "material")
        left = _buckets(shown)
        right = _buckets(" ".join([drawing.material_callout, drawing.weight_callout, drawing.extracted_note]))
        alloys = _alloys(drawing.material_callout + " " + drawing.weight_callout) - _alloys(shown)
        if left and right and left.isdisjoint(right):
            found = True
            draft.warn(f"{drawing.id} / {bom.name}: BOM {sorted(left)} versus drawing {sorted(right)} ({link.relation}).")
            draft.attach_drawing(drawing, knowledge)
        elif alloys:
            found = True
            draft.p(f"{drawing.id} / {bom.name}: drawing alloy {', '.join(sorted(alloys))} is more specific than BOM material {_blank(shown)}.")
            draft.attach_drawing(drawing, knowledge)
    internal = knowledge.drawings["D-017"]
    draft.p("D-017 carries two names in one sheet, Galvo Montage Plade and Galvo Collimator Plade. Neither is forced onto a BOM row.")
    draft.attach_drawing(internal, knowledge)
    if not found:
        draft.p("No linked material families are disjoint.")


def _degraded(draft: Draft, knowledge: Knowledge) -> None:
    draft.p("Eight drawings were distributed only as degraded scans. Their text layer is empty, so dimensions and title blocks are not read from them. The filename and the manifest notice are still evidence of what the file is.")
    for drawing in knowledge.drawings.values():
        if drawing.readable:
            continue
        draft.p(f"{drawing.id} {drawing.title} ({drawing.subsystem}). {drawing.modification_notice}")
        draft.cite("drawing", drawing.id, f"{drawing.id} notice", drawing.modification_notice or drawing.source_path)
    draft.p("Clean sheets are answered from extracted text. A clean sheet can still disagree with the BOM; cleanliness is not truth.")


def _history(draft: Draft, conn: sqlite3.Connection) -> None:
    rows = list_all(conn)
    if not rows:
        draft.p("No corrections have been proposed. The BOM and the drawings are unchanged.")
        return
    draft.p("Review history. Accepted rows change later answers. Rejected rows do not. Nothing here rewrites the CSV or the PDF.")
    for row in rows:
        draft.fact(
            f"#{row['id']} {row['status']} {row['target_label']} {row['field']}",
            f"original {row['original_value'] or '(blank)'} → proposed {row['proposed_value']}. {row['check_summary']}",
        )


def _help(draft: Draft) -> None:
    draft.p("Ask about a part, a subsystem, a material, a recorded supplier, or an interface. If a drawing is known, it opens beside the answer. Reconstructions open for the window clamp frame, the dispenser shaft, and the powder motor plate.")
    draft.p("To file a correction for review, use: Propose a correction: Window Frame material should be 6061 aluminium")
    draft.p("Examples: " + " | ".join(EXAMPLES[:6]))


def _file_correction(draft: Draft, knowledge: Knowledge, conn: sqlite3.Connection, message: str) -> None:
    parsed = parse_proposal(message)
    if not parsed:
        draft.p("Use one of these forms so the target, field, and value are explicit:")
        draft.p("Propose a correction: Window Frame material should be 6061 aluminium")
        draft.p("Correct the material of Window Frame to 6061 aluminium")
        return
    clusters = find_clusters(parsed["target"], knowledge)
    boms = []
    for cluster in clusters:
        for bom in cluster.boms:
            if bom not in boms:
                boms.append(bom)
    if len(boms) != 1:
        names = ", ".join(f"{item.name} ({item.id})" for item in boms) or "nothing"
        draft.warn(f"The correction needs exactly one BOM row. Matched: {names}.")
        draft.abstained = True
        return
    bom = boms[0]
    row = propose(conn, knowledge, bom, parsed["field"], parsed["value"], message.strip())
    draft.correction = {"id": row["id"], "status": row["status"], "summary": row["check_summary"]}
    draft.p(f"Filed correction #{row['id']} on {bom.name} {parsed['field']}. Status: {row['status']}. Answers do not change until this is accepted in Review.")
    draft.fact("Original value", _blank(row["original_value"]))
    draft.fact("Proposed value", row["proposed_value"])
    draft.p(row["check_summary"])
    draft.p(row["check_detail"])
    draft.cite("correction", str(row["id"]), f"Proposal #{row['id']}", row["check_detail"])
    for link in knowledge.links_for_bom(bom.id):
        if link.relation != "rejected":
            draft.attach_drawing(knowledge.drawings[link.drawing_id], knowledge)


def answer(message: str, knowledge: Knowledge, conn: sqlite3.Connection, llm=None) -> dict:
    text = " ".join((message or "").split())

    def finish(draft: Draft) -> dict:
        return narrate(draft.to_dict(), text, llm)

    if not text:
        draft = Draft(message, "help")
        _help(draft)
        return finish(draft)
    if parse_proposal(text):
        draft = Draft(text, "correction")
        _file_correction(draft, knowledge, conn, text)
        return finish(draft)
    folded = fold(text)
    if re.search(r"\b(help|examples|what can you)\b", folded):
        draft = Draft(text, "help")
        _help(draft)
        return finish(draft)
    if re.search(r"correction history|review history|what corrections|audit history|accepted correction", folded):
        draft = Draft(text, "history")
        _history(draft, conn)
        return finish(draft)

    clusters = find_clusters(text, knowledge)
    facets = _facets(text)
    if clusters:
        draft = Draft(text, "part")
        top = clusters[0].specificity(normalize(text))
        primary = [clusters[0]]
        rest = []
        for cluster in clusters[1:]:
            if cluster.specificity(normalize(text)) == top:
                primary.append(cluster)
            else:
                rest.append(cluster)
        if len(primary) > 1:
            draft.p("More than one record matches those words. They are not merged.")
        for cluster in primary:
            _answer_cluster(draft, knowledge, conn, cluster, facets)
        for cluster in rest:
            label_boms = ", ".join(item.name for item in cluster.boms) or "no BOM row"
            label_drawings = ", ".join(item.id for item in cluster.drawings) or "no drawing"
            draft.warn(f"Also matched {label_drawings} / {label_boms}, because a shorter name is inside the question. It is a different record.")
            for drawing in cluster.drawings:
                draft.attach_drawing(drawing, knowledge)
                _cite_drawing(draft, drawing)
        return finish(draft)

    draft = Draft(text, "corpus")
    if re.search(r"organiz|architect|subsystem|overview|what is (this|the) machine|openlpbf", folded):
        draft.intent = "overview"
        _overview(draft, knowledge)
        return finish(draft)
    if re.search(r"disagree|conflict|contradict|inconsistent", folded):
        draft.intent = "conflicts"
        _conflicts(draft, knowledge, conn)
        return finish(draft)
    if re.search(r"which parts|what parts|shared material|are stainless|are aluminium|are aluminum|made of", folded):
        draft.intent = "material"
        _materials(draft, knowledge, conn, text)
        return finish(draft)
    if re.search(r"degraded|noisy|illegible|unreadable|scan", folded):
        draft.intent = "degraded"
        _degraded(draft, knowledge)
        return finish(draft)
    subsystem = None
    for name in SUBSYSTEM_FAMILIES:
        if normalize(name) in normalize(text):
            subsystem = name
    if "optic" in folded:
        subsystem = "Optical"
    if "z-axis" in folded or "z axis" in folded:
        subsystem = "Z-axis"
    if subsystem:
        draft.intent = "subsystem"
        families = SUBSYSTEM_FAMILIES[subsystem]
        sheets = [item for item in knowledge.drawings.values() if item.subsystem == subsystem]
        draft.p(f"{subsystem} has {len(sheets)} drawings in this corpus. Related BOM families: {', '.join(families)}.")
        for drawing in sheets:
            flag = "readable" if drawing.readable else "no extractable text"
            draft.p(f"{drawing.id} {drawing.title} ({drawing.distribution}, {flag}).")
        for drawing in sheets[:1]:
            draft.attach_drawing(drawing, knowledge)
        return finish(draft)

    asked = set(tokens(text))
    claim_hits = []
    for claim in knowledge.claims:
        overlap = asked & set(tokens(claim["snippet"]))
        if len(overlap) >= 2:
            claim_hits.append(claim)
    if claim_hits:
        draft.intent = "system"
        for claim in claim_hits:
            draft.p(claim["statement"])
            draft.cite("readme", claim["id"], "Upstream readme", claim["snippet"])
        return finish(draft)

    draft.intent = "abstain"
    draft.abstained = True
    draft.p("Nothing in the extracted drawings, BOM, or upstream notes supports an answer to that.")
    draft.p("I am not guessing. Ask about a named part, a subsystem, a recorded material, a supplier in the snapshot, or an interface.")
    return finish(draft)
