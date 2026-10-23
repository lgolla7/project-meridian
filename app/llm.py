"""Turn a retrieved evidence packet into the chat reply with a real model call.

The records are gathered first. The model only writes the sentences. It does
not choose which drawing opens, and it does not file a correction.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

SKIP_INTENTS = {"correction", "help", "history"}

SYSTEM = (
    "You are answering an engineer about one OpenLPBF v2 machine. "
    "Use only the evidence packet. If a value is blank, missing, conflicting, or unreadable, say so and do not guess. "
    "Keep a bill-of-materials statement separate from a drawing statement. "
    "If a correction was accepted, use the corrected value and also mention the original bill-of-materials value. "
    "A supplier, order number, or cost is a pinned snapshot, not a current price or a stock check. "
    "If the packet mentions a 3D view, call it a reconstruction from the 2D drawing, not native CAD. "
    "Write a short answer in plain sentences. Do not add part numbers, shops, or dimensions that are not in the packet."
)


class LLMError(Exception):
    pass


class ChatClient:
    def __init__(self, api_key: str, model: str, base_url: str, timeout: float = 45):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def complete(self, question: str, evidence: str) -> str:
        payload = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {
                    "role": "user",
                    "content": f"Question:\n{question}\n\nEvidence packet:\n{evidence}",
                },
            ],
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:400]
            raise LLMError(f"The model API returned {exc.code}. {detail}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"I could not reach the model API. {exc.reason}") from exc
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("The model API replied, but the message body was not a chat completion.") from exc
        text = (text or "").strip()
        if not text:
            raise LLMError("The model API returned an empty answer.")
        return text


def client_from_env() -> ChatClient | None:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return None
    return ChatClient(
        api_key=key,
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
        base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
        or "https://api.openai.com/v1",
    )


def _packet_text(result: dict) -> str:
    lines = []
    for block in result.get("blocks", []):
        if block.get("label"):
            lines.append(f"{block['label']}: {block.get('value', '')}")
        elif block.get("text"):
            lines.append(block["text"])
    if result.get("citations"):
        lines.append("Citations:")
        for cite in result["citations"]:
            lines.append(f"- {cite['source']} {cite['id']}: {cite.get('snippet', '')}")
    if result.get("visuals"):
        names = ", ".join(
            f"{item['id']} {item.get('title', '')}" + (" with a 3D reconstruction" if item.get("has_3d") else "")
            for item in result["visuals"]
        )
        lines.append(f"Drawings opened with this answer: {names}.")
    if result.get("abstained"):
        lines.append("The retrieved records do not support a firm answer. Abstain rather than guess.")
    return "\n".join(lines).strip()


def narrate(result: dict, question: str, llm: ChatClient | None) -> dict:
    """Replace the template sentences with the model reply. Keep warnings, citations, and the open drawing."""
    result["model"] = None
    if result.get("intent") in SKIP_INTENTS:
        return result
    warnings = [block for block in result.get("blocks", []) if block.get("type") == "warn"]
    if llm is None:
        result["blocks"] = [{
            "type": "warn",
            "text": "Set OPENAI_API_KEY and restart the app. I already retrieved the records for this question. The model writes the sentences once that key is available.",
        }] + warnings
        return result
    try:
        prose = llm.complete(question, _packet_text(result))
    except LLMError as exc:
        result["blocks"] = [{"type": "warn", "text": str(exc)}] + warnings
        result["model"] = llm.model
        return result
    paragraphs = [part.strip() for part in prose.split("\n\n") if part.strip()]
    result["blocks"] = [{"type": "p", "text": part} for part in paragraphs] + warnings
    result["model"] = llm.model
    return result
