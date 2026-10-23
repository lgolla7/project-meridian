"""Grounding checks: citations, abstention, visuals, and the correction ledger."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.answer import answer
from app.corrections import connect, resolve
from app.knowledge import load


class EchoModel:
    """Stand-in for the HTTP client. It returns the evidence packet unchanged."""

    model = "echo"

    def __init__(self):
        self.calls = 0

    def complete(self, question: str, evidence: str) -> str:
        self.calls += 1
        self.question = question
        return evidence


def _text(result: dict) -> str:
    parts = []
    for block in result["blocks"]:
        label = block.get("label") or ""
        value = block.get("text") or block.get("value") or ""
        parts.append(f"{label} {value}".strip())
    return "\n".join(parts)


class AnswerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.knowledge = load()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.corr_path = Path(cls.tmp.name) / "corrections.sqlite"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def ask(self, message: str, llm=None) -> dict:
        conn = connect(self.corr_path)
        model = EchoModel() if llm is None else llm
        try:
            result = answer(message, self.knowledge, conn, llm=model)
        finally:
            conn.close()
        if result["intent"] not in {"correction", "help", "history"}:
            self.assertGreater(model.calls, 0)
            self.assertIn(message, model.question)
        return result

    def test_missing_key_does_not_use_a_template(self):
        conn = connect(self.corr_path)
        try:
            result = answer("What is the material of the window frame?", self.knowledge, conn, llm=None)
        finally:
            conn.close()
        text = _text(result)
        self.assertIn("OPENAI_API_KEY", text)
        self.assertNotIn("Custom Box row", text)
        self.assertTrue(any(item["id"] == "D-005" and item["has_3d"] for item in result["visuals"]))
        self.assertIsNone(result["model"])

    def test_window_frame_opens_drawing_and_3d(self):
        result = self.ask("What is the material of the window frame, and does the drawing agree?")
        self.assertFalse(result["abstained"])
        visuals = result["visuals"]
        self.assertTrue(any(item["id"] == "D-005" and item["has_3d"] for item in visuals))
        text = _text(result)
        self.assertIn("6061", text)
        self.assertIn("Aluminium", text)
        self.assertTrue(any(item["source"] == "bom" for item in result["citations"]))
        self.assertTrue(any(item["source"] == "drawing" and item["id"] == "D-005" for item in result["citations"]))

    def test_dispenser_shaft_has_no_borrowed_bom(self):
        result = self.ask("Show the dispenser shaft and its 3D reconstruction.")
        self.assertTrue(any(item["id"] == "D-007" and item["has_3d"] for item in result["visuals"]))
        text = _text(result)
        self.assertIn("not native CAD", text)
        self.assertIn("No BOM row is settled", text)

    def test_powder_canister_abstains_on_holes(self):
        result = self.ask("What are the hole sizes on the powder canister drawing?")
        self.assertTrue(result["abstained"])
        self.assertTrue(any(item["id"] == "D-009" for item in result["visuals"]))
        self.assertIn("degraded", _text(result).lower())

    def test_unsupported_question_abstains(self):
        result = self.ask("What is the laser M2?")
        self.assertTrue(result["abstained"])
        self.assertEqual(result["visuals"], [])

    def test_motor_plate_is_not_merged(self):
        result = self.ask("Is the powder motor plate the same part as the build-plate motor plate?")
        text = _text(result)
        self.assertIn("Not the same part", text)
        ids = {item["id"] for item in result["visuals"]}
        self.assertIn("D-010", ids)
        self.assertIn("D-030", ids)
        self.assertNotIn("D-026", ids)

    def test_front_door_interfaces_are_bidirectional(self):
        result = self.ask("What interfaces with the front door?")
        text = _text(result)
        self.assertIn("Front Side Box", text)
        self.assertIn("Front door hinge", text)
        self.assertTrue(any(item["id"] == "D-001" for item in result["visuals"]))

    def test_recorded_cost_has_a_snapshot_caveat(self):
        result = self.ask("What supplier and cost are recorded for the laser safety window?")
        text = _text(result)
        self.assertIn("Masentia", text)
        self.assertIn("DKK2400.00", text)
        self.assertIn("pinned BOM snapshot", text)
        self.assertIn("(blank)", text)

    def test_stainless_list_keeps_sources_apart(self):
        result = self.ask("Which parts are recorded as stainless steel?")
        text = _text(result)
        self.assertIn("Left Side Box", text)
        self.assertIn("D-002", text)
        self.assertNotIn("Window Frame", text)

    def test_build_volume_comes_from_the_readme(self):
        result = self.ask("What is the build volume and laser?")
        self.assertFalse(result["abstained"])
        self.assertIn("250", _text(result))
        self.assertTrue(any(item["source"] == "readme" for item in result["citations"]))

    def test_correction_changes_the_answer_and_keeps_the_original(self):
        before = self.ask("What is the material of the window frame?")
        self.assertNotIn("Material used in answers", _text(before))
        filed = self.ask("Propose a correction: Window Frame material should be 6061 aluminium")
        self.assertEqual(filed["correction"]["status"], "pending")
        pending = self.ask("What is the material of the window frame?")
        self.assertNotIn("Material used in answers", _text(pending))
        conn = connect(self.corr_path)
        try:
            resolve(conn, filed["correction"]["id"], "accepted", "Title block says 6061.")
        finally:
            conn.close()
        after = self.ask("What is the material of the window frame?")
        text = _text(after)
        self.assertIn("6061 aluminium", text)
        self.assertIn("Original BOM material", text)
        self.assertIn("Aluminium", text)
        history = self.ask("What corrections have been accepted?")
        self.assertIn("accepted", _text(history))


if __name__ == "__main__":
    unittest.main()
