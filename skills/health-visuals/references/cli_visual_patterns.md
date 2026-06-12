# CLI Visual Patterns

Use these as seed patterns before inventing a new visual.

## Meeting Stress Leaderboard

Ranks meetings or meeting clusters by biometric elevation versus a local
baseline. Requires calendar events and overlapping heart-rate or stress samples.
Default privacy: title clusters, role labels, pseudonyms, or attendee counts.

```text
MEETING STRESS   mean HR over surrounding baseline
dbpm   z     elev  meeting cluster        attendees
+11.3  1.54   57%  planning block         role_pm, role_eng_a
 +5.5  0.97   49%  review block           role_manager, role_eng_b
 -2.9 -0.43    5%  solo focus             self
```

## Recovery Gate

Compares readiness and sleep against today or tomorrow's calendar load. Requires
readiness/sleep and upcoming or same-day calendar minutes.

```text
RECOVERY GATE   Fri 2026-06-12
readiness   72  [=======---] ok
sleep       81  [========--] good
meetings   330m [!!!!!!!!--] heavy

verdict: protect 14:00-16:00
```

## Day Shape Barcode

Compresses sleep, stress, calendar, email, and food timing into one row.

```text
DAY SHAPE   2026-06-05
sleep   [#######.]  6h42
stress  __/^^^\____
cal     ..##.####..##..
email   _/^^\__/^\____
food    ...B....L....D.
```

## Workload Outcome Matrix

Buckets calendar load and email load against stress or sleep outcomes. Requires
30+ days for stronger confidence.

```text
WORKLOAD MATRIX   90d
                  light email    heavy email
light meetings    stress 0.8h    stress 1.4h
heavy meetings    stress 2.1h    stress 3.8h  << hotspot
```

## Coverage Trust Ledger

Shows whether each domain is complete enough to trust the visual.

```text
DATA COVERAGE   last 30d
oura daily       29/30  [#########.]
heart rate       22/30  [#######...]
calendar         30/30  [##########]
food              6/30  [##........]  sparse
```
