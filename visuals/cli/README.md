# CLI Visual Catalog

This folder collects terminal-only visualization ideas for local health,
calendar, email, food, and activity data. These are design specs and prompt
assets, not a runtime export path. Keep them dependency-free, privacy-safe, and
usable from plain text logs.

## Principles

- Render with ASCII first; ANSI color is optional and must have a no-color mode.
- Use local aggregates, role labels, pseudonyms, or counts by default.
- Do not print raw attendee identities, email addresses, calendar descriptions,
  precise locations, OAuth tokens, or credential file contents.
- Always show coverage or confidence when a visual depends on sparse data.
- Keep analysis and rendering separate: analysis produces structured facts,
  renderers turn those facts into terminal output.

## Build Structure

Visuals are meant to be built in layers:

```text
health_query / health_feature_query / health_analyze
        -> structured rows, metrics, or analysis results
        -> visual_specs.json entry declares fields, coverage, and privacy
        -> renderer produces plain ASCII with optional ANSI color
        -> health-visuals skill uses prompt-level semantic routing
```

The `health-visuals` skill is the self-writing workflow. It should answer on the
first pass: use an existing catalog entry when the semantic intent fits, or
draft a new visual spec, `mockups/<visual_id>.txt` sketch, and analysis/tool
handoff when the request is novel. Keep routing examples in the skill prompt and
reference notes, not in `visual_specs.json`.

## Catalog

1. `meeting_stress_leaderboard` ranks meetings or meeting clusters by heart-rate
   or stress elevation against a nearby baseline.
2. `attendee_effect_board` estimates per-attendee marginal stress effects using
   pseudonyms or role labels.
3. `recovery_gate` compares today's readiness and sleep against tomorrow's
   calendar load.
4. `calendar_load_skyline` shows occupied meeting blocks by weekday and hour.
5. `day_shape_barcode` compresses sleep, stress, calendar, email, and meals into
   a single day row.
6. `workload_outcome_matrix` buckets meeting load and email load against stress
   or sleep outcomes.
7. `sleep_debt_heatstrip` highlights sleep debt, bedtime drift, and context
   labels across a rolling window.
8. `baseline_drift_board` compares recent RHR, HRV, SpO2, and sleep baselines
   against the prior period.
9. `stress_waterfall` shows daily stress accumulation and recovery resets.
10. `workout_recovery_lane` compares workout timing/intensity with next-day
    readiness.
11. `chronotype_planner` turns tomorrow's first meeting and recent sleep need
    into a target bedtime.
12. `coverage_trust_ledger` shows whether Oura, calendar, email, and food data
    are complete enough to trust a result.

See `visual_specs.json` for structured fields and `mockups/` for terminal
sketches.
