---
name: health-visuals
description: Use when the user asks for terminal, CLI, ASCII, ANSI, dashboard, leaderboard, chart, visualization, visual idea, or new visual output for local health, wearable, calendar, email, food, workout, sleep, stress, recovery, or readiness data. If no existing visual fits, design a new privacy-safe CLI visual spec and mockup.
---

# Health Visuals

Use this skill to answer with terminal-only visuals or to design a new visual
when the current catalog does not fit the user's moment.

## Workflow

1. Identify the user's intent: compare, rank, explain a day, plan ahead, check
   coverage, show a trend, or explore an unknown pattern.
2. Check the existing catalog first:
   - `visuals/cli/visual_specs.json`
   - `visuals/cli/mockups/`
   - If packaged without the repo catalog, read
     `references/cli_visual_patterns.md`.
3. If a catalog visual fits, use it. Query data with existing health tools before
   filling values: `health_coverage`, `health_query`, `health_feature_query`,
   `health_calendar_peek`, `health_analysis_plan`, or `health_analyze`.
4. If no visual fits, synthesize a new visual:
   - Name it in `snake_case`.
   - State purpose, required data, minimum coverage, privacy default, and caveat.
   - Render a plain-text mockup that works without color.
   - Include `safe` and `detail` privacy modes. Default to `safe`.
   - Say what tool or analysis pack should produce the structured facts later.
5. If working in the repo, save the new candidate under `visuals/cli/`:
   - Add or update a `visual_specs.json` entry.
   - Add `mockups/<visual_id>.txt`.
   - Add tests or update `tests/test_visual_catalog.py`.

## Design Rules

- ASCII first; ANSI color optional and never required for meaning.
- Keep analysis and rendering separate. Do not bury data queries inside a text
  renderer.
- Show coverage, confidence, or `thin data` when sample size is weak.
- Use "associated with" rather than causal language.
- Redact event titles, attendees, email addresses, email subjects, food text,
  locations, and credential paths by default.
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
