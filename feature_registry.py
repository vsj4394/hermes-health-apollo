from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureDefinition:
    key: str
    grain: str
    required_domains: tuple[str, ...]
    missing_semantics: str
    builder_name: str
    source_tables: tuple[str, ...]


FEATURE_VERSION = "plan-b-v1"

FEATURE_DEFINITIONS = {
    "sleep_score": FeatureDefinition("sleep_score", "day", ("oura",), "null", "daily_oura_metric", ("oura_daily",)),
    "readiness_score": FeatureDefinition("readiness_score", "day", ("oura",), "null", "daily_oura_metric", ("oura_daily",)),
    "stress_high_seconds": FeatureDefinition("stress_high_seconds", "day", ("oura",), "null", "daily_oura_metric", ("oura_daily",)),
    "recovery_high_seconds": FeatureDefinition("recovery_high_seconds", "day", ("oura",), "null", "daily_oura_metric", ("oura_daily",)),
    "sleep_duration_seconds": FeatureDefinition("sleep_duration_seconds", "day", ("oura",), "null", "daily_oura_metric", ("oura_daily",)),
    "deep_sleep_seconds": FeatureDefinition("deep_sleep_seconds", "day", ("oura",), "null", "daily_oura_metric", ("oura_daily",)),
    "bedtime_minutes_since_noon": FeatureDefinition("bedtime_minutes_since_noon", "day", ("oura",), "null", "daily_oura_metric", ("oura_daily",)),
    "meeting_minutes": FeatureDefinition("meeting_minutes", "day", ("calendar",), "zero", "daily_calendar_metric", ("calendar_daily",)),
    "meeting_count": FeatureDefinition("meeting_count", "day", ("calendar",), "zero", "daily_calendar_metric", ("calendar_daily",)),
    "email_received_count": FeatureDefinition("email_received_count", "day", ("email",), "zero", "daily_email_metric", ("email_daily",)),
    "meal_count": FeatureDefinition("meal_count", "day", ("food",), "missing", "daily_food_metric", ("food_logs",)),
    "food_total_estimated_calories": FeatureDefinition("food_total_estimated_calories", "day", ("food",), "missing", "daily_food_metric", ("food_logs",)),
    "last_meal_hour": FeatureDefinition("last_meal_hour", "day", ("food",), "missing", "daily_food_metric", ("food_logs",)),
    "late_meal_flag": FeatureDefinition("late_meal_flag", "day", ("food",), "missing", "daily_food_metric", ("food_logs",)),
    "workout_count": FeatureDefinition("workout_count", "day", ("oura",), "zero", "daily_workout_metric", ("oura_workouts",)),
    "exercise_minutes": FeatureDefinition("exercise_minutes", "day", ("oura",), "zero", "daily_workout_metric", ("oura_workouts",)),
    "days_since_workout": FeatureDefinition("days_since_workout", "day", ("oura",), "missing", "days_since_workout", ("oura_workouts",)),
    "missed_planned_workout": FeatureDefinition("missed_planned_workout", "day", ("oura",), "missing", "habit_adherence", ("oura_workouts", "entities")),
}
