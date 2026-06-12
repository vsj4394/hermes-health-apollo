# Interpretation Guardrails

Terminal health visuals are decision aids, not diagnosis.

- Say "associated with" instead of "caused by" unless the user supplied a
  controlled experiment.
- Prefer medians, confidence labels, and minimum sample thresholds over precise
  claims from thin data.
- Show `thin data`, `partial`, or `needs sync` directly in the visual when
  coverage is weak.
- Explain local baselines: nearby HR/stress windows, rolling personal averages,
  or previous-period comparisons.
- Keep sharing mode conservative: no raw people names, emails, event titles,
  food descriptions, locations, or health exports.
- For biometric stress, heart-rate, or ranking visuals, do not show raw
  third-party names or raw meeting titles even when the user asks for detail.
  Use pseudonyms, role labels, or buckets unless the user gives explicit
  local-only confirmation and understands it should not be shared.
