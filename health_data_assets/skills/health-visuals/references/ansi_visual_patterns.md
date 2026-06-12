# ANSI Visual Patterns

Use ANSI color as a semantic overlay, not the primary carrier of meaning.

## Semantic Color Tokens

- `[G3]` strong positive / excellent
- `[G2]` positive / healthy
- `[G1]` mild positive / safe
- `[Y2]` warm caution / soft warning
- `[Y1]` caution / mixed
- `[O1]` orange warning / notable strain
- `[O2]` deep orange / pre-risk
- `[R1]` elevated / risk
- `[R2]` strongest warning / overload / high strain
- `[B1]` structural accent / labels / framing
- `[N0]` missing / sparse / hidden
- `[RESET]` clear styling

## Mapping Guidance

- recovery, readiness, strong coverage, calming effects -> green
- moderate load, partial coverage, mixed outcomes -> yellow
- meaningful debt, strain, or overload that is not yet full red -> orange
- overload, stress, strain, high-risk deltas -> red
- hidden, sparse, unavailable fields -> neutral gray

## Apollo Examples

```text
readiness   [G2]72[RESET]   [G2]██████████████[RESET][N0]░░░░░░[RESET]  good
meetings   [R2]330m[RESET]  [R2]████████████████[RESET][N0]░░░░[RESET]  heavy
food        [O1] 6/30[RESET] [O1]████[RESET][N0]░░░░░░░░░░░░░░[RESET] sparse
```

```text
cardio      [G2]37%[RESET]   [G2]███████[RESET][N0]░░░░░░[RESET]
strength    [Y2]31%[RESET]   [Y2]██████[RESET][N0]░░░░░░[RESET]
recovery    [G2]22%[RESET]   [G2]████[RESET][N0]░░░░░░░░[RESET]
```

## Rules

- keep output readable when ANSI escapes are stripped
- do not color raw sensitive content; privacy rules come first
- avoid rainbow palettes; stay in the green/yellow/orange/red/neutral family unless a
  structural accent is needed
- use stronger red for cumulative overload, not for every small negative delta
- use orange for clearly-off but not worst-case states like sleep debt,
  elevated strain, or middling readiness under load
