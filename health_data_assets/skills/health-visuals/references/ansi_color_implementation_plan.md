# Apollo ANSI Color Visuals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable ANSI color rendering layer for Apollo terminal visuals so positive, caution, risk, and missing-data states are visually obvious without changing the underlying analysis semantics.

**Architecture:** Keep data analysis, semantic scoring, and text rendering separate. Add one shared palette/token layer, then have each renderer opt into semantic color roles such as `good`, `risk`, `caution`, `missing`, and `accent` rather than hardcoding escape bytes inside business logic.

**Tech Stack:** Python, plain terminal ANSI SGR sequences, existing health query/analysis tools, skill/reference-driven visual guidance, pytest.

---

## Scope

- Introduce a shared ANSI palette and token resolver for Apollo visuals.
- Keep monochrome output as the default-safe fallback.
- Add color-capable renderers only for the catalog visuals that already have stable mockups.
- Ensure privacy rules survive color mode unchanged.

## Proposed File Structure

- Create: `renderers/ansi_palette.py`
  - shared color constants and helper functions like `paint(role, text, enabled=True)`
- Create: `renderers/health_visuals.py`
  - renderer entry points for catalog visuals, structured around semantic roles
- Create: `tests/test_ansi_palette.py`
  - palette token and reset behavior
- Create: `tests/test_health_visual_renderers.py`
  - renderer snapshots for monochrome and ANSI-enabled output
- Modify: `skills/health-visuals/SKILL.md`
- Modify: `skills/health-visuals/references/ansi_visual_patterns.md`
- Modify: `visuals/cli/README.md`
  - document color rules, fallback behavior, and renderer contract
  - tell the agent when to request color mode and when to stay monochrome
- Modify: `commands.py`
  - add a debug/admin entry point for rendering a chosen visual from structured data if needed later

## Recommended Semantic Roles

- `accent`
  - headings, labels, chips, structure
- `good`
  - recovery, strong readiness, solid coverage, calming effect
- `good_soft`
  - mild positive movement, safe but not excellent
- `caution`
  - mixed states, moderate load, partial coverage
- `risk`
  - high strain, elevated stress, negative delta
- `risk_strong`
  - strongest warning/highest stress bucket
- `missing`
  - hidden, sparse, incomplete, or unavailable fields

## Rendering Rules

- Never use color as the only signal. Keep numbers, words, and ASCII bars readable without color.
- Add a global `color: bool` or `ansi: bool` flag at render time.
- Default to monochrome unless:
  - user explicitly asks for color, or
  - the renderer is being previewed/debugged locally.
- Keep raw ANSI escapes out of analysis logic and out of long-lived structured data.
- Use color only at final render time.

## Implementation Tasks

### Task 1: Add shared ANSI palette helper

**Files:**
- Create: `renderers/ansi_palette.py`
- Test: `tests/test_ansi_palette.py`

- [ ] Add palette constants for the Apollo semantic roles.
- [ ] Add `paint(role, text, enabled)` that wraps `text` in ANSI SGR codes only when `enabled=True`.
- [ ] Add `reset()` helper or inline reset constant.
- [ ] Add tests for:
  - enabled role wraps text with the expected prefix and reset
  - disabled role returns plain text
  - unknown role fails clearly or falls back to neutral by design

### Task 2: Define renderer contract

**Files:**
- Create: `renderers/health_visuals.py`
- Modify: `visuals/cli/README.md`
- Test: `tests/test_health_visual_renderers.py`

- [ ] Add a renderer interface that accepts:
  - `visual_id`
  - structured `data`
  - `color`
  - `privacy_mode`
- [ ] Keep the renderer pure: input facts in, formatted string out.
- [ ] Document that semantic scoring happens before rendering.

### Task 3: Implement the first three renderers

**Files:**
- Modify: `renderers/health_visuals.py`
- Test: `tests/test_health_visual_renderers.py`

- [ ] Implement `recovery_gate`
- [ ] Implement `coverage_trust_ledger`
- [ ] Implement `baseline_drift_board`
- [ ] Add snapshot-style tests for monochrome and ANSI output

Why these first:
- they have the clearest positive/caution/risk semantics
- they are the easiest to evaluate visually
- they do not require dense timeline layout logic first

### Task 4: Implement the matrix and leaderboard renderers

**Files:**
- Modify: `renderers/health_visuals.py`
- Modify: `skills/health-visuals/references/ansi_visual_patterns.md`
- Test: `tests/test_health_visual_renderers.py`

- [ ] Implement `meeting_stress_leaderboard`
- [ ] Implement `attendee_effect_board`
- [ ] Implement `workload_outcome_matrix`
- [ ] Add semantic color hints in the skill references

### Task 5: Implement timeline-style visuals

**Files:**
- Modify: `renderers/health_visuals.py`
- Test: `tests/test_health_visual_renderers.py`

- [ ] Implement `day_shape_barcode`
- [ ] Implement `stress_waterfall`
- [ ] Implement `sleep_debt_heatstrip`
- [ ] Implement `calendar_load_skyline`

These need careful contrast choices because they compress many signals into one line.

### Task 6: Implement planning and exercise visuals

**Files:**
- Modify: `renderers/health_visuals.py`
- Test: `tests/test_health_visual_renderers.py`

- [ ] Implement `chronotype_planner`
- [ ] Implement `workout_recovery_lane`
- [ ] Implement `workout_streak_ladder`
- [ ] Implement `strain_readiness_ribbon`
- [ ] Implement `training_mix_board`
- [ ] Ensure bedtime/risk windows and next-day recovery use the same palette semantics as earlier visuals

### Task 7: Wire the renderers into a callable debug surface

**Files:**
- Modify: `commands.py`
- Modify: `health_data_entry.py`
- Test: `tests/test_commands.py`

- [ ] Add a debug/admin render command such as:
  - `hermes health render-visual recovery_gate --color`
- [ ] Keep it local-only and deterministic
- [ ] Use existing query/analysis tool outputs as input rather than recomputing business logic

### Task 8: Update skill guidance

**Files:**
- Modify: `skills/health-visuals/SKILL.md`

- [ ] Teach the skill to prefer monochrome by default for copied/shared output
- [ ] Teach it to use ANSI color only when the user asks for terminal color or local preview
- [ ] Preserve privacy defaults regardless of color mode

## Verification Plan

- Unit tests for ANSI palette helpers
- Snapshot tests for each renderer in:
  - monochrome mode
  - ANSI mode
- Manual terminal verification in a real shell for:
  - dark background
  - light background
  - copy/paste behavior with and without ANSI stripping
- Confirm all visuals remain understandable when ANSI is disabled

## Risks

- Too much color can make dense ASCII visuals unreadable
- Raw escape codes can pollute copied logs or GitHub snippets
- Red/green-only semantics can be inaccessible without shape/text reinforcement
- Different terminals render 256-color palettes differently

## Recommendation

Start with `recovery_gate`, `coverage_trust_ledger`, and `baseline_drift_board`, then validate the palette in a real terminal before rolling it across the denser visuals and the new exercise lane/ladder/board set.
