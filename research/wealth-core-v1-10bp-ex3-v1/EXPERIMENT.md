# Wealth Core V1 10 bp + Experiment 3 / Research Champion EX3

## Objective

Take the frozen $100k Wealth Core V1 replay with the 10 basis-point NAV cash reserve and layer the frozen Experiment 3 / Research Champion Candidate-A exposure controller on top.

This is research only. No production or main changes.

## Underlying 10 bp Wealth Core authority

- run: `34283531740`
- artifact: `10079799925`
- generated source SHA-256: `44a9914be859eb7f76ca747aaa66a41e19a557a2095da0a707ea99575898c4e0`
- canonical PIT dataset SHA-256: `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`
- initial capital: $100,000
- measurement: 2006-07-31 through 2026-07-31
- dividend lag: **1 session**
- whole shares only
- buffer: 10 bp of current NAV

## EX3 authority

Experiment 3 is the Research Champion Candidate-A controller profile `strategy9-e3-research-champion-v1`.

The one-session-dividend controller lineage was formally recertified by:

- source branch: `research/champion-dividend-lag-1-recertification`
- source head: `1d3ab06a0b6c1ef5db4939bbecfe24953ae2195d`
- successful run: `34071569702`
- artifact: `10001317230`
- artifact SHA-256: `803b1b8288d77fc9c275cec5ebac91f8bac23ba030dad3dfb5d523fceed2415f`
- status: `PRODUCTION_EQUIVALENT_CERTIFIED`
- profile: `strategy9-e3-research-champion-v1`
- profile SHA-256: `1101e99ae9ca327278d79d5334556ca01bbc167e2cb3410ab4902b89550e5c26`
- certified generated source SHA-256: `bbd6783d0cd0e5d1662a0146190962e5845cc4b6bdb8feb50d0c7788f90a6077`
- dividend lag: **1 session**

Frozen EX3 center:

- LDRC_REC: 8 sessions
- LDRC_R20: -8.5%
- LDRC_V: +11.0%
- LDRC_DD: -10.0%
- divergence SPY floor: 0.0%
- full-recovery r40 floor: 0.0%
- FAST damaged breadth: 88.0%
- healthy damaged ceiling: 63.0%

## Important implementation fact

The exact 0 bp and 10 bp Wealth Core replays already executed Candidate A / EX3 in parallel with the underlying Wealth Core book. The daily files contain `control_allocation`, `control_nav`, `A_allocation`, `A_nav`, and reasons. The generated source assigns Candidate A directly to the control path.

Therefore this experiment does **not** need another historical market replay. It verifies the existing replay byte-for-byte, proves `control == Candidate A / EX3` on every measured session, and extracts the combined system result.

## Acceptance gates

- exact baseline and 10 bp evidence hashes reproduce
- canonical PIT dataset hash is unchanged
- both summaries report dividend lag = 1
- whole-share 10 bp core PASS remains intact
- `control` metrics equal Candidate A metrics for 0 bp and 10 bp
- `control_nav == A_nav` on all 5,032 sessions
- `control_allocation == A_allocation` on all 5,032 sessions
- `control_reason == A_reason` on all 5,032 sessions
- generated source contains the frozen EX3 parameters
- generated source contains the 10 bp close and open reserve checks
- ranking-path differences, holdings differences, native-target differences, and EX3 allocation differences are reported separately

## Outputs

- `output/RESULT.json`
- `output/INSIGHTS.md`
- `output/allocation-divergence.csv`
- `output/run.log`
