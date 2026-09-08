# Wealth Core V1 vs V2 — current corrected full-PIT findings

Status: **completed A/B finding / research decision record**  
Date: 2026-09-08 (America/Los_Angeles)  
Branch: `research/wealth-core-v2-current-v1-ab`  
Workflow run: `34232324866`  
Evidence artifact: `10059963661`  
Artifact digest: `sha256:952b78e3be4fb8f6f9562ef1ec78acc414af1111fd59d35c00cb4f4a1ecf567c`

## 1. Purpose

Re-run the Wealth Core V1 versus V2 slot-funding comparison on the **current corrected production-equivalent lineage**, because the earlier formal V1/V2 A/B was anchored to a superseded economic lineage.

The primary research question is the effect on **pure Wealth Core**. Sentinel / Research Champion is decomposed separately and is not treated as part of Wealth Core performance.

## 2. Exact control and corpus

The V1 control is the corrected production-equivalent full-PIT executable from successful certification run `34071569702` at commit:

`1d3ab06a0b6c1ef5db4939bbecfe24953ae2195d`

Control artifact:

- artifact id: `10001317230`
- digest: `sha256:803b1b8288d77fc9c275cec5ebac91f8bac23ba030dad3dfb5d523fceed2415f`
- generated-source SHA256: `bbd6783d0cd0e5d1662a0146190962e5845cc4b6bdb8feb50d0c7788f90a6077`
- normalized AST SHA256: `435d42ac56f160a665588a997335a923c25110404972e262aa6e47058b3befde`

The A/B required a **byte-exact regenerated V1 executable** before permitting V2 to run. The gate passed:

`PASS_BYTE_EXACT_GENERATED_SOURCE`

Both variants use the same canonical PIT corpus:

`5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`

Replay identity:

- replay mode: `fullpit`
- measurement start: `2006-07-31`
- end session: `2026-07-31`
- sessions: `5,032`
- financial-grade dividend settlement lag: `1` session
- final security-type reconstruction: current corrected final-truth path
- capacity participation cap: none

Therefore this comparison is not the obsolete 5.85% / 6.14% formal lineage and must not be conflated with it.

## 3. Economic change under test

Only this economic domain changed:

`wealth_core_entry_slot_funding`

V1 retains the existing cash-clipped admission rule.

V2 applies the previously reviewed `wealth-core-v2-full-whole-share-target-v1` funding rule:

- compute the full whole-share target from current equity and entry weight;
- require sufficient **uncommitted cash** before reserving the slot;
- reserve cash persistently with the pending slot;
- next-open fills are bounded by that reserved budget;
- upward gaps may clip shares within the reserved budget;
- no other Wealth Core economics are intentionally changed.

Patch authority commit:

`26b324f4da0f80cf790048103a0d92c1c0df3920`

V2 generated-source SHA256:

`c4aa2213ec2448f2af6e71158da5339c7b04681486a0e4aad3ee2dd4919b026a`

## 4. Primary result — pure Wealth Core

Pure Wealth Core is measured from `shadow_equity`, before Sentinel / Research Champion exposure control.

| Metric | Wealth Core V1 | Wealth Core V2 | Delta |
|---|---:|---:|---:|
| CAGR | **15.246650%** | **13.778824%** | **-1.467826 pp** |
| Ending multiple | **17.084077x** | **13.220620x** | -22.61% ending wealth |
| Max drawdown | **-48.0442%** | **-50.3078%** | worse by 2.2636 pp |
| Daily Sharpe (252) | **0.804477** | **0.718216** | -0.086260 |
| Buys | 505 | 474 | -31 |
| Sells | 424 | 398 | -26 |
| Average held names | **22.6789** | **20.1669** | -2.5119 |
| Sessions at 25 held names | **1,217** | **6** | -1,211 |

V2 held fewer names than V1 on **81.34% of sessions**. Across the full horizon it averaged **2.51 fewer holdings**.

### Primary conclusion

**V2 materially degrades Wealth Core itself.**

The failure is present before Sentinel is applied. The V2 rule therefore should not be promoted as the Wealth Core slot correction.

## 5. Sentinel decomposition

The full-account `A_nav` result is shown only to decompose how much additional CAGR the frozen Sentinel / Research Champion exposure layer added on top of each Wealth Core path.

| Version | Pure Wealth Core CAGR | With Sentinel CAGR | Sentinel lift |
|---|---:|---:|---:|
| **V1** | **15.246650%** | **18.800889%** | **+3.554239 pp** |
| **V2** | **13.778824%** | **15.653812%** | **+1.874988 pp** |

Additional full-system metrics:

| Metric | V1 + Sentinel | V2 + Sentinel |
|---|---:|---:|
| CAGR | **18.800889%** | **15.653812%** |
| Ending multiple | **31.363500x** | **18.332637x** |
| Max drawdown | -24.9137% | **-23.0319%** |
| Daily Sharpe (252) | **1.036337** | 0.931785 |

Interpretation:

- Sentinel adds value to both paths in CAGR terms.
- Sentinel adds approximately **+3.55 percentage points** to V1.
- Sentinel adds approximately **+1.87 percentage points** to V2.
- The V2 core degradation is not a controller-only artifact; it already exists in pure Wealth Core.
- The V2 full system trails V1 by **3.147077 percentage points of CAGR**.

## 6. V2 funding-path behavior

V2 telemetry over the full-PIT run:

- reservations: `476`
- rejected admissions for insufficient uncommitted cash: `277,191`
- next-open gap-clipped fills: `249`
- gap-cancelled fills: `0`

This explains the large reduction in portfolio occupancy. V2 transforms the slot problem into a much broader admission-suppression rule: if the book cannot fund the complete fresh target, the candidate is denied the slot.

The observed result is extensive unused physical capacity relative to V1, not merely removal of pathological microscopic positions.

## 7. Relationship to the microscopic-slot forensic finding

Issue #335 established that the microscopic-slot problem is real and systemic in V1-style cash-clipped admission semantics.

The exact Median-5 observer replay showed:

- 426 reservations / 426 fills;
- 96 reservations (22.5%) were cash-limited at decision time;
- 22 fills were below 1% of their nominal target;
- LLYVK entered at approximately 0.423% of nominal target and subsequently occupied a physical slot for hundreds of sessions;
- RCUS entered as one share, approximately 0.00003883% of nominal target, and still occupied a full physical slot;
- these holdings were **born tiny**; they were not created by failed exits, split remnants, stale marks, or liquidation defects;
- sell plumbing was complete in the forensic run: all 363 sell signals became sell attempts and fills.

Therefore the underlying semantic problem remains:

> A severely underfunded holding can acquire the same binary physical slot rights as a properly funded position.

But the new A/B establishes that **V2's proposed remedy is too broad**. It changes the rule from “do not let microscopic capital permanently monopolize a slot” to “do not admit any new episode unless essentially the complete target can be funded.” The latter sacrifices too much deployment and harms core performance.

These are not equivalent problems.

## 8. Correct interpretation of V1 and V2

The correct research posture after this A/B is:

1. **Do not declare V1 economically clean.** The microscopic-slot pathology remains factual.
2. **Do not promote current V2.** It fixes the pathology by over-restricting admissions and reduces pure Wealth Core CAGR from 15.25% to 13.78%.
3. The next correction should target the actual scarce-capacity problem more surgically, while preserving useful partial deployment where possible.
4. No follow-up repair should be selected by Sentinel headline CAGR.

## 9. Research sequencing decision

The agreed sequencing principle is now:

### Stage 1 — Wealth Core first

- Run Wealth Core candidates as **pure Wealth Core**.
- Diagnose stock-selection, ownership-state, admission, replacement, and slot-capacity economics without Sentinel masking or amplifying the result.
- Improve/fix the core until its economics and robustness are satisfactory.
- Freeze the chosen Wealth Core candidate.

### Stage 2 — Sentinel second

Only after Wealth Core is frozen:

- layer Sentinel / Research Champion exposure control on top;
- measure incremental CAGR, drawdown, Sharpe, exposure behavior, and robustness;
- tune/test controller hypotheses against the frozen core rather than allowing simultaneous core/controller changes.

This separation prevents the exposure controller from hiding a bad core change or making a good core change appear bad because of path-dependent controller interaction.

## 10. Frozen controls for subsequent work

Until deliberately superseded by a new certified candidate, use these as the current control values:

### Wealth Core V1

- pure Wealth Core CAGR: **15.2466501237%**
- max drawdown: **-48.0442181486%**
- Sharpe: **0.8044766146**
- ending multiple: **17.0840770674x**

### Current rejected Wealth Core V2

- pure Wealth Core CAGR: **13.7788238652%**
- max drawdown: **-50.3077674506%**
- Sharpe: **0.7182161292**
- ending multiple: **13.2206201212x**

### Sentinel decomposition controls

- V1 + Sentinel CAGR: **18.8008888001%**
- V1 Sentinel lift: **+3.5542386764 pp**
- V2 + Sentinel CAGR: **15.6538115544%**
- V2 Sentinel lift: **+1.8749876892 pp**

## 11. Decision

**Current Wealth Core V2 (`full_whole_share_target_v1`) is rejected as the slot-funding solution.**

The microscopic-slot defect remains open and requires a more surgical semantic repair.

For future Wealth Core experiments, pure Wealth Core performance is the primary decision surface. Sentinel is to be layered only after a Wealth Core candidate has been selected and frozen.
