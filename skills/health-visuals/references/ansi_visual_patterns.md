# ANSI Visual Patterns

Use ANSI color as a semantic overlay, not the primary carrier of meaning.

## Semantic Color Tokens

- `[G3]` strong positive / excellent
- `[G2]` positive / healthy
- `[G1]` mild positive / safe
- `[Y1]` caution / mixed
- `[R1]` elevated / risk
- `[R2]` strongest warning / overload / high strain
- `[B1]` structural accent / labels / framing
- `[N0]` missing / sparse / hidden
- `[RESET]` clear styling

## Mapping Guidance

- recovery, readiness, strong coverage, calming effects -> green
- moderate load, partial coverage, mixed outcomes -> yellow
- overload, stress, strain, high-risk deltas -> red
- hidden, sparse, unavailable fields -> neutral gray

## Apollo Examples

```text
readiness   [G2]72[RESET]  [G2][=======---][RESET] ok
meetings   [R2]330m[RESET] [R2][!!!!!!!!--][RESET] heavy
food        [R1] 6/30[RESET] [R1][##........][RESET] sparse
```

```text
cardio      [G2]37%[RESET]   [G2][#######.....][RESET]
strength    [Y1]31%[RESET]   [Y1][######......][RESET]
recovery    [G2]22%[RESET]   [G2][####........][RESET]
```

## Rules

- keep output readable when ANSI escapes are stripped
- do not color raw sensitive content; privacy rules come first
- avoid rainbow palettes; stay in the green/yellow/red/neutral family unless a
  structural accent is needed
- use stronger red for cumulative overload, not for every small negative delta
