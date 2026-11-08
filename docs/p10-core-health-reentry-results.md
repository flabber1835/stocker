# P10 three-healthy-close experiment: completed comparison

The owner-authorized single P10 pilot completed on 2026-11-08. Faster re-entry
increased growth and worsened maximum drawdown. This supports recovery-delay
cost as a mechanism, while demonstrating the protection lost by the blanket
three-healthy-close rule. It does not establish an improvement in both objectives.

The [predeclared experiment](p10-core-health-reentry-experiment.md) was unchanged
during the successful run. Both accounts use the same admitted P10 Core history,
2018-01-02 through 2026-07-31: 126 formation observations and 2,156 measured
sessions. The original Core, frozen controller sources, inputs and all prior
financial results remain unchanged. There were zero new Core transitions or new
campaign sessions. This is inspected historical research, not unseen validation.

| Measure | Existing Sentinel | Three healthy closes |
| --- | ---: | ---: |
| CAGR | 16.3264% | 18.0370% |
| Maximum drawdown | -29.1387% | -30.7988% |
| Final value from $50,000 | $182,880.83 | $207,268.77 |
| Allocation changes after initial establishment | 17 | 20 |
| Total recorded allocation turnover | 13.1930993781 | 14.2930993781 |

The growth gain is 1.7106 percentage points per year. The worst drawdown is
1.6601 percentage points deeper. Close targets differed on 150 sessions.
The experiment recovers approximately 40% of the existing Sentinel CAGR gap
against P10 Core alone; it does not remove the gap or dominate the existing rule.

## Where the difference came from

These are ordinary calendar-period returns calculated from the existing saved
NAV ratios, not annualized values for partial years:

| Period | Existing Sentinel | Three healthy closes |
| --- | ---: | ---: |
| 2019 | 11.65% | 12.02% |
| 2020 | 31.75% | 33.76% |
| 2022 | -4.75% | -6.98% |
| 2024 | 28.63% | 37.76% |
| January-July 2026 | 32.25% | 40.69% |

Calendar returns in 2018, 2021, 2023 and 2025 were unchanged. The largest
benefits occurred in 2024 and 2026 recoveries. Protection deteriorated in the
prolonged 2022 decline. The registered rule is not retuned after this result.

For the existing August8-October8,2024 defensive window, recorded funded returns
were +1.61% for the baseline and +8.72% for the candidate. For March31-April17,2026,
they were +1.58% and +7.65%. For January19-August10,2022, they were +0.43% and
-2.21%. These compare actual canonical account NAVs over identical intervals,
including switching-day overnight exposure and costs; they are not substitutes
for canonical daily open/close accounting.

## Execution, review and admission

Successful [run42497621094](https://github.com/flabber1835/stocker/actions/runs/42497621094),
job128783278380, used head `332458bde09b0fcdfae79b712d08fed923c12e2a` and request
SHA256 `efa7318185e6c15346040e3788d73a71f981a625264ca2781d0e78a4843be60d`.
The original baseline targets and every funded-account field reproduced exactly.
Both worker and independent reviewer positively stopped with exit0, no OOM and
no wait error. The reviewer checked both paths, every target/factor/NAV, all
monthly account continuations and all 103 monthly reports per account, using
independent vector equations and rational metrics.

Measured times inside the experiment launcher were 11.55 seconds for baseline
authentication/source preparation, 8.96 seconds for the paired worker and 5.27
seconds for independent review; 25.89 seconds including export. Frozen-input and
runtime transfer, checkout, dependency installation, queueing and local
development are additional time. Two earlier caller-path setup failures were
corrected and preserved; neither began financial calculation. The final local
DATA/AST suite passed 24 tests in4.13 seconds, including the exact failure
regressions. No canonical runtime was executed locally.

Output artifact13623508717 is 1,364,208 bytes, SHA256
`0cb4532d9850c72e6840bb03344b3c0cecdcf0c97425cc0bdc0832ebed203f84`.
Its encrypted member is 1,360,765 bytes, SHA256
`d4edc21cfeb18ddc99a6be0da7dc874ecce14d0cafb2f6a1dfe876587ff1d608`.
Manifest SHA256 is
`6a98550aad2d7c59b64591909b3da0560158e9e8a6b29943a455f4f26c6f1715`.
Independent local DATA admission verified the complete outer ZIP and four public
members, AES-GCM authentication before plaintext interpretation, and every one
of the 16 manifest members/1,747,462 logical bytes. Both 2,156-row account journal
commitments matched and the worker/reviewer reports agreed exactly. No local
controller, financial-account advancement, replay or restore was performed.

Durable detailed results are stored in the task evidence directory as
`p10-reentry-generation3-admitted-results.json`; the original stopped receipt
continues to say pending admission and is not rewritten. New result metadata
records the separate independent artifact admission. The original twelve-variant
campaign remains paused. No P00 follow-up, parameter grid, production, PAPER,
LIVE, deployment, merge or other financial run was launched.
