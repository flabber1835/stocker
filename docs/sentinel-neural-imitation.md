# Neural imitation of the hindsight exposure policy

The owner requested a neural network trained to behave like the previously
computed ideal Sentinel. This is an offline research extension of PR #597,
based on verified main `69b4a78a25610bf4aaee27eb4956a0611d26d124`. Preserve
the running fractional replay, its source, canonical Core and all production
controller/execution code. No model is installed or given broker authority.

## Frozen experiment, before training

Use the authenticated 2006-07-31 through 2019-04-16 snapshot already retained by
the exposure oracle. The teacher maximizes growth within recorded Sentinel's
daily-close drawdown cap, using only 0%, 55%, and 100%, with the same scalar
costs, overnight ownership and next-open timing. Recompute and match the earlier
full-period oracle before fitting the final all-history research model.
The earlier selected optimum contains no 55% actions; do not manufacture them
to balance classes. A three-output model remains capable of all three actions,
but a class without positive teacher examples is unsupported by this sample.

Do not split a full-history hindsight path into training labels: an optimal
earlier action can depend on later returns. Instead solve each period's oracle
independently, with no returns beyond that period's final close:

| Use | Label return sessions | Role |
| --- | --- | --- |
| Train | After 63 feature sessions through 2012-12-31 | Fit weights and scaling |
| Validation | 2013-01-02 through 2015-12-31 | Select epoch by cross-entropy |
| Model-held-out test | 2016-01-04 through 2019-04-16 | Score once after model export |

Each period starts at the preceding completed close with recorded Sentinel's
held allocation and unit wealth. All policies share that initial holding and
the same returns/costs. The close's feature vector predicts the following open's
action; the old holding earns the overnight return. Training omits feature
warmup. Fixed original deployment is retained if a teacher includes it. Teacher
drawdown starts at each period's own baseline, not at an unseen earlier peak.
If unconstrained growth meets the cap, use that exact solution; otherwise use
the existing exact constrained search and refuse resource exhaustion.

Inputs are 38 features available at the decision close: Core and SPY log-return
lags 1-5; 5/20/63-session momentum; 5/20/63-session return volatility;
20/63-session rolling drawdown and deviation from average value; Core-minus-SPY
20/63 momentum; canonical Core cash fraction and occupied-slot fraction; and
recorded Core healthy/impaired and native fast/slow severe flags. No absolute
date, time index, future return, oracle previous action, strategy-account NAV,
broker holdings or realized execution exposure is an input. These recorded
controller flags remain functions of the unchanged Core/market history; neural
decisions do not feed back into them. Raw breadth is not present in this compact
snapshot, so this first model uses its recorded health flags rather than
inventing breadth values or rerunning stock selection.

Use a small feed-forward classifier: 38 inputs, hidden layers 16 and 8 with
tanh activation, and three softmax outputs. Fit with scikit-learn 1.7.2 Adam,
learning rate 0.001, L2 alpha 0.01, batch size 64, and random seed 17. Train at
most 400 epochs; manually stop after 40 epochs without validation cross-entropy
improvement greater than 0.000001. Shuffle only training batches. Disable the
library's automatic randomized validation split. Standardize using training
means/scales only, then clip to [-5,5]. Freeze architecture, seed, features and
decision rule before observing test performance. Select the largest predicted
probability, resolving exact ties in action order 0/55/100. No post-test
confidence threshold, trading gate or hyperparameter search is added.

Export the selected model and scaling to strict, finite, shape-checked JSON;
inference uses NumPy and never deserializes executable pickle. Verify exported
probabilities against the fitted model, reload the artifact, and write test
predictions before computing test oracle labels or performance. Retain hashes,
source checkpoint, dependencies, feature order, partitions, all epoch losses,
probabilities, actions and monthly results. A test-label/return change must not
alter training features, training teacher, scaling or selected-model inputs.

After the frozen test is scored, separately refit on all available features
and the authenticated full-period ideal labels for the already selected number
of epochs, regardless of the test result. Label this artifact ALL_HISTORY_REFIT:
its next unseen return session is after April 16, 2019. Never reuse its
in-sample scores as the held-out test. The model selected on 2013-2015 remains a
separate preserved artifact for reproducible evaluation.

## Reporting and validation

Report train/validation/test teacher class counts, imitation accuracy, confusion
matrix and cross-entropy. Compare the test model's CAGR, wealth multiple,
maximum drawdown, exposure switches and modeled turnover against current
Sentinel, always-Core, SPY, BIL and the test-period hindsight teacher. Include
monthly output and an offline interactive report. Accuracy alone is not the
strategy objective; a classifier can make costly mistakes or overtrade even
with reasonable directional accuracy.

The test dates are excluded from this model's fitting and checkpoint selection,
but were inspected during prior research. This is chronological model holdout,
not an untouched research holdout or proof of future predictability. Retain the
inherited data/accounting limitations. Later replay data and forward observation
are separate qualification evidence; no production replacement follows from
this request.

Targeted tests cover feature prefix/future invariance, strict finite inputs,
close-to-next-open alignment, independent label horizons, training-only scaling,
absence of invented classes, deterministic training and serialized inference,
source identity and constrained teacher accounting. Remove relevant guards in
isolated processes to demonstrate their falsifiers. Do not run the full suite.

Implementation references: [MLPClassifier 1.7](https://scikit-learn.org/1.7/modules/generated/sklearn.neural_network.MLPClassifier.html)
and [training-only preprocessing](https://scikit-learn.org/stable/common_pitfalls.html).
Install research-only dependencies into a dedicated volume, not the production
image or protected backtest. Limit workers to one BLAS thread, half a CPU and
1 GiB RAM; model inference has no network or broker access.

## Completed first training result

The frozen implementation ran from commit
`72aaf42a1f4477fcc548634ff9929196d8e1aae6` in the pinned replay image. The
787-parameter network selected epoch 42 and stopped after epoch 82. Training
has 1,553 examples (first decision 2006-10-27, first outcome 2006-10-30);
validation has 756, and test has 827. Teacher counts at 0/55/100 are respectively
709/0/844, 327/0/429 and 357/0/470. All three period caps are nonbinding for
their exact maximum-growth teacher. The all-history refit uses 3,136 examples,
1,393 at zero and 1,743 at full exposure, for the preselected 42 epochs.

Held-out economics use the 2015-12-31 close as common baseline and returns from
2016-01-04 through 2019-04-16:

| Policy | CAGR | Multiple | MaxDD | Changes |
| --- | ---: | ---: | ---: | ---: |
| Neural model | 4.3862% | 1.1517 | 20.8066% | 101 |
| Current Sentinel | 8.8290% | 1.3211 | 20.6137% | 6 |
| Always Core / training-majority action | 9.6629% | 1.3547 | 23.4211% | 1 |
| SPY | 13.5007% | 1.5170 | 19.3387% | — |
| BIL | 0.9639% | 1.0321 | 0.0873% | 0 |
| Hindsight teacher | 113.8648% | 12.2033 | 0.9380% | 340 |

The model matches 54.8972% of test teacher actions, below the 56.8319% accuracy
of always choosing the training-majority class, 100%. Balanced accuracy is
49.1397%. It identifies only 25 of 357 teacher-zero days (7.00% recall), and
mistakenly goes to zero on 41 teacher-full days. Its mean exposure is 92.02%,
versus Sentinel's 90.06% and the hindsight teacher's 56.83%. The model generally
stays invested, interrupted by short exits that do not reproduce ideal timing.
No test prediction selects 55%, consistent with its absence from teacher labels.

Both model and Sentinel spend 66 sessions at zero in this test, but with very
different sequencing; Sentinel also has 36 sessions at 55%. The neural model's
101 exposure changes incur a 9.6113% compounded overlay-cost drag, versus
0.3894% for Sentinel. Of the -0.1371678 log-wealth gap, -0.0971491 (70.83%) is
additional overlay cost and -0.0400187 is gross return timing. Before those
overlay costs, CAGR is still lower: 7.6411% versus 8.9581%. The first model fails
both the growth and imitation comparison. This does not establish that every
neural approach must fail; it supplies no evidence for replacing Sentinel.

Training/validation/test accuracies are 59.37% / 55.95% / 54.90%. The separate
all-history model fits 60.91% of its own teacher labels; that is an in-sample
score, not a second held-out result. No architecture, threshold, feature or
epoch was retuned after test results were observed.

Retained local evidence is
`.codex-tmp/sentinel-neural-imitation-20261115/run-001/`, including both JSON
models, learning history, test probabilities, teacher labels, daily paths, all
40 monthly metric rows, provenance and a self-contained interactive report.
Artifact SHA256:

- Evaluation model: `a1c7f884de5d094f10522534e45a72b5975eb2456593ffee2259c2f9ad6b878d`
- Test predictions, frozen before test-label scoring: `b41dbe6743a6bb19b774c37d3b63ceb5442c9f561969dc19cfd47dd6feb01f5a`
- All-history refit: `bc58ed0f45452035590abe8c5e06f524ff3fb147b3c1c99d3fa14b7f2d664d66`

Validation:

```bash
python -B -m pytest tests/sentinel/test_exposure_neural.py \
  tests/sentinel/test_exposure_oracle.py tests/sentinel/test_exposure_logic.py \
  -q -p no:cacheprovider
```

This reports **67 passed**. After renaming the serialized schema field to avoid
a Pydantic method-name warning and strengthening the source-identity falsifier,
the final targeted command
`python -B -m pytest tests/sentinel/test_exposure_neural.py -q -p no:cacheprovider`
reports **18 passed**. Isolated mutations of label horizon, feature/next-open
alignment, training-only scaling, action schema and teacher source identity each
make their selected falsifier fail. No repository source file is modified by
these mutation checks.

A separate read-only audit verifies serialized model/probability hashes,
training-only scaling, all 827 decision/outcome alignments, independent Decimal
neural NAV arithmetic, every policy's metrics, and all neural/Sentinel/SPY
monthly arithmetic. Its additive cost/timing attribution reconciles exactly
within numeric tolerance. Both model JSON exports reproduce fitted inference.
The earlier full-period oracle is recomputed and matches before final refit.
The HTML embeds its library; 15 plot traces, lengths and displayed values pass
programmatic checks. Interactive browser visual inspection was unavailable.
