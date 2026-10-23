"""Render a PDF page to PNG for the viewer.

The text extractor and the picture are separate on purpose. A degraded scan can
still be looked at while the answer refuses to invent text that was not extracted.
"""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium

from app.config import DATA

PAGES = DATA / "pages"


def render_page(pdf_path: Path, page_number: int, drawing_id: str) -> Path:
    PAGES.mkdir(parents=True, exist_ok=True)
    target = PAGES / f"{drawing_id}-{page_number}.png"
    if target.exists() and target.stat().st_size > 0:
        return target
    document = pdfium.PdfDocument(str(pdf_path))
    try:
        page = document[page_number - 1]
        image = page.render(scale=2).to_pil()
        image.save(target, format="PNG")
    finally:
        document.close()
    return target
