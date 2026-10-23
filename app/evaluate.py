"""Run the public questions and record latency, citations, and the correction change."""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from app.answer import EXAMPLES, answer
from app.config import DATA
from app.corrections import connect, resolve
from app.knowledge import load
from app.llm import client_from_env


def _plain(result: dict) -> str:
    lines = []
    for block in result["blocks"]:
        if block.get("label"):
            lines.append(f"{block['label']}: {block.get('value', '')}")
        else:
            lines.append(block.get("text", ""))
    return "\n".join(lines)


def main() -> None:
    knowledge = load()
    client = client_from_env()
    DATA.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        conn = connect(Path(tmp) / "corrections.sqlite")
        rows = []
        for question in EXAMPLES:
            if question.lower().startswith("propose"):
                continue
            started = time.perf_counter()
            result = answer(question, knowledge, conn, llm=client)
            elapsed = round((time.perf_counter() - started) * 1000, 2)
            rows.append({
                "question": question,
                "intent": result["intent"],
                "abstained": result["abstained"],
                "latency_ms": elapsed,
                "visuals": result["visuals"],
                "citation_count": len(result["citations"]),
                "answer": _plain(result),
            })
        before = answer("What is the material of the window frame?", knowledge, conn, llm=client)
        proposal = answer(
            "Propose a correction: Window Frame material should be 6061 aluminium",
            knowledge,
            conn,
            llm=client,
        )
        resolve(conn, proposal["correction"]["id"], "accepted", "Checked against D-005.")
        after = answer("What is the material of the window frame?", knowledge, conn, llm=client)
        conn.close()
    report = {
        "method": (
            f"I retrieve the records, then {client.model} writes the sentences."
            if client
            else "I retrieve the records. OPENAI_API_KEY was unset, so this report stores the missing-key reply."
        ),
        "model": client.model if client else None,
        "questions": rows,
        "correction": {
            "before": _plain(before),
            "proposal_check": proposal["correction"],
            "after": _plain(after),
        },
    }
    path = DATA / "evaluation.json"
    path.write_text(json.dumps(report, indent=2))
    abstained = sum(1 for row in rows if row["abstained"])
    print(f"Wrote {path} ({len(rows)} questions, {abstained} abstained)")


if __name__ == "__main__":
    main()
