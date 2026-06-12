# Health Visual Brief

Use this prompt when asking an agent or renderer to produce a terminal-only
health visualization from local Hermes data.

Inputs:

- User question or visual name.
- Available data domains and coverage summary.
- Structured analysis output, if one already exists.
- Privacy mode: `safe` by default, `detail` only when the user explicitly asks.
  Even in `detail` mode, do not reveal raw third-party names or raw meeting
  titles in biometric stress, heart-rate, or ranking visuals without explicit
  local-only confirmation.

Output contract:

1. State the visual title and date range.
2. Render a plain-text table or chart that works without color.
3. Include coverage and caveats when data is sparse, partial, or inferred.
4. Label correlations as associations, not causes.
5. Redact or bucket sensitive calendar/email/person details. `detail` mode may
   show the user's own exact values, but biometric rankings involving other
   people still need pseudonyms, role labels, or attendee counts by default.

Do not include raw OAuth data, credential paths, calendar descriptions, email
subjects, email bodies, precise locations, or unredacted attendee identities.
