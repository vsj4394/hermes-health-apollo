# Terminal ASCII Patterns

Use these layout patterns when building Apollo terminal visuals. They are
generic display primitives, not routing rules.

## Progress Bars

```text
Progress: ████████████░░░░░░░░ 60%
Sleep (7.5h)  ███████████████░░░░░ 75%
```

Guidance:
- `█` / `░` for simple binary fill
- keep width stable across rows
- pair bars with numbers so monochrome logs still work

## Sparklines

```text
Last 7 days: ▁▂▄▃▅▆█
Weight (kg): 75.5 ─▂▃▄▃▂▁─ 74.8
```

Guidance:
- use for compact trend context
- always pair with endpoints or a short trend note
- avoid using sparklines as the only signal in a health answer

## Box-Drawing Tables

```text
┌──────────┬───────┬────────┐
│ Metric   │ Value │ Status │
├──────────┼───────┼────────┤
│ Sleep    │ 7.5h  │ ✓      │
│ Recovery │ 72    │ ⚠      │
└──────────┴───────┴────────┘
```

Guidance:
- use when row alignment matters more than density
- good for coverage, scorecards, and multi-metric daily summaries
- prefer plain ASCII fallback if copy/paste fidelity is uncertain

## Dashboards

```text
═══════════════════════════════════════
  TODAY: 2026-06-12
═══════════════════════════════════════

METRICS             Value       vs Avg
───────────────────────────────────────
Sleep               7.5h        +0.3h
Readiness           72          -4
Stress              46m         +8m
```

Guidance:
- use for grouped summaries
- use `═` for top-level sections, `─` for inner sections
- keep widths consistent

## Weekly Grids

```text
            Mon Tue Wed Thu Fri Sat Sun  Total
Exercise     ✓   ✗   ✗   ✓   ✗   ✓   ✗   3/7
Sleep (h)   7.5 8.0 6.0 7.0 7.5 8.5 7.0  Avg: 7.4
```

Guidance:
- use for compliance, streaks, and routine adherence
- pair symbols with totals and averages

## Status Semantics

Use these consistently:

- `✓` done / good / healthy
- `✗` missed / failed / blocked
- `○` pending / neutral
- `↑` improving
- `↓` declining
- `→` stable
- `⚠` attention needed
- `🔥` active streak

For Apollo visuals, never rely on emoji or symbols alone; pair them with text or
numbers.
