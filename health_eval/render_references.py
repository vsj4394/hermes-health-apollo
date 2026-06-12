"""Render reference placeholders from a fixture database."""

from __future__ import annotations

import json
from pathlib import Path

from .export_ground_truth import export_ground_truth
from .reference_templates import QUESTIONS, QUESTION_METADATA, render_reference_answer


def render_references(
    db_path: str | Path,
    output_path: str | Path | None = None,
) -> dict:
    """Render all current reference placeholders."""

    facts = export_ground_truth(db_path)
    payload = {
        question_id: {
            "question": question,
            "ground_truth_facts": facts,
            "reference_answer": render_reference_answer(question_id, facts),
            "must_include": list(QUESTION_METADATA[question_id]["must_include"]),
            "common_failures": list(
                QUESTION_METADATA[question_id]["common_failures"]
            ),
            "pass_criteria": QUESTION_METADATA[question_id]["pass_criteria"],
        }
        for question_id, question in QUESTIONS.items()
    }

    if output_path is not None:
        Path(output_path).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    return payload
