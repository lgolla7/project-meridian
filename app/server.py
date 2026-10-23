"""HTTP API and the static UI. One process, no separate database server."""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.answer import EXAMPLES, answer
from app.config import DIAGRAMS, KNOWLEDGE_DB, WEB
from app.llm import client_from_env
from app.corrections import connect as connect_corrections
from app.corrections import list_all, resolve
from app.knowledge import catalog_payload, load
from app.pages import render_page

app = FastAPI(title="Project Meridian")
_knowledge = None
_lock = threading.Lock()


def knowledge():
    global _knowledge
    if _knowledge is None:
        if not KNOWLEDGE_DB.exists():
            from app.extract import build
            build()
        _knowledge = load()
    return _knowledge


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ReviewIn(BaseModel):
    note: str = ""


@app.get("/api/health")
def health():
    data = knowledge()
    client = client_from_env()
    return {
        "bom_rows": len(data.boms),
        "drawings": len(data.drawings),
        "reconstructions": list(data.reconstructions),
        "model": client.model if client else None,
    }


@app.get("/api/examples")
def examples():
    return {"questions": EXAMPLES}


@app.get("/api/catalog")
def catalog():
    return catalog_payload(knowledge())


@app.get("/api/graph")
def graph():
    return knowledge().graph()


@app.get("/api/reconstructions/{drawing_id}")
def reconstruction(drawing_id: str):
    item = knowledge().reconstructions.get(drawing_id)
    if not item:
        raise HTTPException(404, "No reconstruction for this drawing")
    return item


@app.get("/api/drawings/{drawing_id}")
def drawing_meta(drawing_id: str):
    drawing = knowledge().drawings.get(drawing_id)
    if drawing is None:
        raise HTTPException(404, "Unknown drawing")
    return {
        "id": drawing.id,
        "title": drawing.title,
        "pages": drawing.pages,
        "distribution": drawing.distribution,
        "subsystem": drawing.subsystem,
    }


@app.get("/api/drawings/{drawing_id}/pages/{page_number}")
def drawing_page(drawing_id: str, page_number: int):
    drawing = knowledge().drawings.get(drawing_id)
    if drawing is None or page_number < 1 or page_number > drawing.pages:
        raise HTTPException(404, "Unknown page")
    path = render_page(Path(drawing.file_path), page_number, drawing_id)
    return FileResponse(path, media_type="image/png")


@app.get("/api/drawings/{drawing_id}/file")
def drawing_file(drawing_id: str):
    drawing = knowledge().drawings.get(drawing_id)
    if drawing is None:
        raise HTTPException(404, "Unknown drawing")
    path = Path(drawing.file_path)
    if not path.exists():
        raise HTTPException(404, "Drawing file missing")
    return FileResponse(path, media_type="application/pdf", filename=f"{drawing_id}.pdf")


@app.get("/api/diagrams/{diagram_id}/file")
def diagram_file(diagram_id: str):
    for diagram in knowledge().diagrams:
        if diagram["id"] == diagram_id:
            path = DIAGRAMS / diagram["file_name"]
            if not path.exists():
                break
            return FileResponse(path, media_type="image/png")
    raise HTTPException(404, "Unknown diagram")


@app.get("/api/corrections")
def corrections():
    conn = connect_corrections()
    try:
        return {"corrections": list_all(conn)}
    finally:
        conn.close()


@app.post("/api/chat")
def chat(body: ChatIn):
    conn = connect_corrections()
    try:
        with _lock:
            return answer(body.message, knowledge(), conn, llm=client_from_env())
    finally:
        conn.close()


@app.post("/api/corrections/{correction_id}/accept")
def accept(correction_id: int, body: ReviewIn):
    return _review(correction_id, "accepted", body.note)


@app.post("/api/corrections/{correction_id}/reject")
def reject(correction_id: int, body: ReviewIn):
    return _review(correction_id, "rejected", body.note)


def _review(correction_id: int, status: str, note: str):
    conn = connect_corrections()
    try:
        with _lock:
            row = resolve(conn, correction_id, status, note)
        if row is None:
            raise HTTPException(404, "Unknown correction")
        return row
    finally:
        conn.close()


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/assets", StaticFiles(directory=WEB), name="assets")


def main():
    import uvicorn
    uvicorn.run("app.server:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
