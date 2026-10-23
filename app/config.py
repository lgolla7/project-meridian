"""Paths used by extraction, the API, and the browser UI."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "dataset"
DRAWINGS = DATASET / "drawings"
MANIFEST = DATASET / "manifest.json"
BOM_CSV = DATASET / "context" / "openlpbf-bom.csv"
README = DATASET / "context" / "openlpbf-upstream-readme.md"
DIAGRAMS = DATASET / "context" / "diagrams"
DATA = ROOT / "data"
KNOWLEDGE_DB = DATA / "knowledge.sqlite"
CORRECTIONS_DB = DATA / "corrections.sqlite"
WEB = ROOT / "web"
