from __future__ import annotations

PLAN_C_QUESTIONS = {
    "hap_e03": {
        "prompt": "Why was I stressed yesterday?",
        "variant": "calendar_email_stress",
        "analysis_id": "calendar_email_stress_association",
        "requires": ["health_analysis_plan", "health_coverage", "health_analyze"],
    },
    "hap_e04": {
        "prompt": "On my most stressful days, was it more meetings or email?",
        "variant": "calendar_email_stress",
        "analysis_id": "calendar_email_stress_association",
        "requires": ["health_analysis_plan", "health_coverage", "health_analyze"],
    },
    "hap_e06": {
        "prompt": "Which foods seem to hurt my sleep?",
        "variant": "food_sleep",
        "analysis_id": "food_sleep_association",
        "requires": ["health_analysis_plan", "health_coverage", "health_analyze"],
    },
    "hap_e07": {
        "prompt": "What days do I miss exercise?",
        "variant": "missed_workouts",
        "analysis_id": "exercise_adherence",
        "requires": ["health_analysis_plan", "health_coverage", "health_analyze"],
    },
    "hap_e11": {
        "prompt": "Which foods hurt my sleep?",
        "variant": "thin_food_sleep",
        "analysis_id": "food_sleep_association",
        "requires": ["health_analysis_plan", "health_coverage", "health_analyze"],
        "expects_reason": "minimum_sample_size_not_met",
    },
    "hap_e12": {
        "prompt": "Why did you say meetings were linked to stress?",
        "variant": "provenance_focus",
        "analysis_id": "calendar_email_stress_association",
        "requires": [
            "health_analysis_plan",
            "health_coverage",
            "health_analyze",
            "health_analysis_explain",
        ],
    },
}

PLAN_C_REQUIRED_COPY_MODULES = (
    "sync_control.py",
    "tool_registry.py",
    "semantic_layer.py",
    "feature_registry.py",
    "feature_engineering.py",
    "analysis_registry.py",
    "analysis_tools.py",
    "onboarding.py",
)
