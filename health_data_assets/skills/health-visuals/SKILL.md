---
name: health-visuals
description: Use when the user asks for terminal, CLI, ASCII, ANSI, dashboard, leaderboard, chart, visualization, visual idea, or new visual output for local health, wearable, calendar, email, food, workout, sleep, stress, recovery, or readiness data. Select an existing CLI visual by semantic intent, or design a new privacy-safe first-pass CLI visual spec and mockup in the same answer.
---

# Health Visuals

Use this skill to answer with terminal-only visuals. Route by semantic intent in
this skill prompt and reference notes, not by routing fields in JSON. The catalog
describes visual specs; it is not a prompt router.

## Workflow

1. Identify the user's intent: compare, rank, explain a day, plan ahead, check
   coverage, show a trend, or explore an unknown pattern.
2. Check the existing catalog first:
   - `visuals/cli/visual_specs.json`
   - `visuals/cli/mockups/`
   - packaged mirror: `health_data_assets/visuals/cli/`
   - If packaged without the repo catalog, read
     `references/cli_visual_patterns.md`.
3. If a catalog visual fits, use it. Query data with existing health tools before
   filling values: `health_coverage`, `health_query`, `health_feature_query`,
   `health_event_query`, `health_calendar_peek`, `health_analysis_plan`, or
   `health_analyze`.
4. For a novel visual intent, synthesize a first-pass visual immediately:
   - Name it in `snake_case`.
   - State purpose, required data, minimum coverage, privacy default, and caveat.
   - Render a plain-text mockup that works without color.
   - Include `safe` and `detail` privacy modes. Default to `safe`.
   - If a needed derived field does not exist yet, label it unavailable or
     proposed instead of inventing values.
   - Say what tool or analysis pack should produce the structured facts later.
5. If working in the repo, save the new candidate under `visuals/cli/`:
   - Add or update a `visual_specs.json` entry.
   - Add `mockups/<visual_id>.txt`.
   - Update `visuals/cli/README.md` when the catalog list changes.
   - Add tests or update `tests/test_visual_catalog.py`.

## Routing Cues

These examples belong in the skill instructions because the model uses them to
choose behavior. Do not copy them into `visual_specs.json`.

- Meeting stress, heart-rate spikes during meetings, coworker stress, or meeting
  title requests: use `meeting_stress_leaderboard`; use `attendee_effect_board`
  when the request ranks people or attendees.
- Readiness versus today's or tomorrow's calendar: use `recovery_gate`.
- A whole-day terminal strip, barcode, or timeline: use `day_shape_barcode`.
- Meeting/email workload against stress, sleep, or readiness: use
  `workload_outcome_matrix`.
- Missing data, sync quality, or whether a chart can be trusted: use
  `coverage_trust_ledger`.
- Caffeine timing, sleep latency, next-day readiness, or any other visual not in
  the catalog: produce a new first-pass visual spec and mockup in the answer.

## Design Rules

- ASCII first; ANSI color optional and never required for meaning.
- Keep analysis and rendering separate. Do not bury data queries inside a text
  renderer.
- Show coverage, confidence, or `thin data` when sample size is weak.
- Use "associated with" rather than causal language.
- Redact event titles, attendees, email addresses, email subjects, food text,
  locations, and credential paths by default.
- Even in `detail` mode, do not display raw third-party names or raw meeting
  titles in biometric stress, heart-rate, or ranking visuals. Use explicit user
  confirmation plus a non-shareable local-only warning before considering it.
- Never print OAuth tokens, client secrets, raw database exports, or local private
  paths.

## Creation Template

```text
VISUAL: <title>
id: <snake_case_id>
purpose: <why this is useful now>
data: <tables/tools/features needed>
minimum coverage: <threshold>
privacy default: <safe redaction/bucketing behavior>

<plain terminal mockup>

caveat: <association/coverage warning>
next implementation: <analysis/tool/renderer needed>
```
