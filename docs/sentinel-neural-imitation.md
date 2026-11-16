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
