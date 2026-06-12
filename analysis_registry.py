from __future__ import annotations


ANALYSIS_PACKS = {
    "calendar_email_stress_association": {
        "analysis_id": "calendar_email_stress_association",
        "display_name": "Calendar and email stress association",
        "intents": [
            "was it more meetings or email",
            "meetings or email associated with stress",
            "meeting or email days line up with stress sleep readiness",
            "most stressful days meetings email",
            "why was i stressed",
        ],
        "required_features": [
            "meeting_minutes",
            "email_received_count",
            "stress_high_seconds",
            "sleep_score",
            "readiness_score",
        ],
        "default_window_days": 90,
        "minimums": {"outcome_days": 14, "high_signal_days": 4, "low_signal_days": 4},
        "method": "cohort_contrast",
        "answer_policy": {
            "causal_language": False,
            "diagnosis": False,
            "evidence_first": True,
        },
    },
    "food_sleep_association": {
        "analysis_id": "food_sleep_association",
        "display_name": "Food and sleep association",
        "intents": [
            "which foods hurt my sleep",
            "late meals and sleep",
            "food sleep association",
        ],
        "required_features": [
            "meal_count",
            "food_total_estimated_calories",
            "late_meal_flag",
            "sleep_score",
            "sleep_duration_seconds",
        ],
        "default_window_days": 90,
        "minimums": {"outcome_days": 14, "exposed_days": 4, "unexposed_days": 4},
        "method": "cohort_contrast",
        "answer_policy": {
            "causal_language": False,
            "diagnosis": False,
            "evidence_first": True,
        },
    },
    "exercise_adherence": {
        "analysis_id": "exercise_adherence",
        "display_name": "Exercise adherence",
        "intents": [
            "what days do i miss exercise",
            "missed workout days",
            "exercise routine adherence",
        ],
        "required_features": ["workout_count", "missed_planned_workout"],
        "default_window_days": 60,
        "minimums": {"routine_days": 6},
        "method": "adherence",
        "answer_policy": {
            "causal_language": False,
            "diagnosis": False,
            "evidence_first": True,
        },
    },
    "exercise_recovery_association": {
        "analysis_id": "exercise_recovery_association",
        "display_name": "Exercise and recovery association",
        "intents": [
            "does exercise help my recovery",
            "workout and readiness",
            "exercise recovery association",
        ],
        "required_features": [
            "workout_count",
            "exercise_minutes",
            "readiness_score",
            "recovery_high_seconds",
        ],
        "default_window_days": 90,
        "minimums": {"outcome_days": 14, "exercise_days": 4, "non_exercise_days": 4},
        "method": "cohort_contrast",
        "answer_policy": {
            "causal_language": False,
            "diagnosis": False,
            "evidence_first": True,
        },
    },
}


def catalog_entry(analysis_id: str) -> dict:
    pack = ANALYSIS_PACKS[analysis_id]
    return {
        "analysis_id": pack["analysis_id"],
        "display_name": pack["display_name"],
        "default_window_days": pack["default_window_days"],
        "requires_follow_up": False,
    }
