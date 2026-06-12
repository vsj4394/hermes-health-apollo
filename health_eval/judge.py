"""Deterministic judge for local health-data eval lanes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from .checker import extract_numbers


JUDGE_MODEL_ID = "deterministic-reference-judge-v1"
PROMPT_PATH = Path(__file__).with_name("judge_prompt.txt")
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def judge_prompt_hash() -> str:
    return hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest()


def judge_answer(
    *,
    question: str,
    answer: str,
    reference: str,
    tool_trace: list[dict] | None = None,
) -> dict:
    """Score one answer against deterministic references and trace evidence."""

    trace = tool_trace or []
    answer_lower = answer.lower()
    reference_lower = reference.lower()
    reference_numbers = extract_numbers(reference)
    answer_numbers = extract_numbers(answer)
    reference_dates = DATE_RE.findall(reference)
    answer_dates = DATE_RE.findall(answer)

    has_reference_text = reference_lower in answer_lower
    numbers_match = all(number in answer_numbers for number in reference_numbers)
    dates_match = all(date in answer_dates for date in reference_dates)
    used_health_query = any(item.get("tool") == "health_query" for item in trace)

    data_correctness = 32 if has_reference_text and numbers_match and dates_match else 14
    efficiency = 6 if used_health_query and len(trace) <= 3 else 2
    calibration = 7 if any(word in answer_lower for word in ("fixture", "data", "based")) else 3
    communication = 9 if question and answer.strip() else 0
    dimension_scores = {
        "data_correctness": data_correctness,
        "driver_decomposition": 10 if used_health_query else 4,
        "efficiency": efficiency,
        "baseline_relative": 10 if "fixture" in answer_lower or "baseline" in answer_lower else 5,
        "trend_decomposition": 10 if used_health_query else 4,
        "causation_discipline": 8 if "hypothesis" in answer_lower or "fixture" in answer_lower else 4,
        "calibration": calibration,
        "communication": communication,
    }
    composite = sum(dimension_scores.values())
    passed = composite >= 70 and data_correctness == 32 and used_health_query

    return {
        "question": question,
        "answer": answer,
        "reference": reference,
        "status": "deterministic",
        "dimension_scores": dimension_scores,
        "composite": composite,
        "pass": passed,
        "tool_calls": len(trace),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.smoke:
        result = judge_answer(
            question="Why was I stressed yesterday?",
            answer=(
                "Based on the fixture data, the reference says: "
                "The highest-stress fixture day is 2026-06-06 with "
                "7200 high-stress seconds."
            ),
            reference=(
                "The highest-stress fixture day is 2026-06-06 with "
                "7200 high-stress seconds."
            ),
            tool_trace=[{"tool": "health_query"}],
        )
        print(
            json.dumps(
                {
                    "status": "deterministic",
                    "lane": "judge",
                    "judge_model_id": JUDGE_MODEL_ID,
                    "judge_prompt_hash": judge_prompt_hash(),
                    "pass": result["pass"],
                },
                sort_keys=True,
            )
        )
        return 0
    parser.error("only --smoke is implemented in the skeleton")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
