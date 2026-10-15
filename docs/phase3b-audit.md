# Phase 3B — Evaluation audit before changes

This audit was completed before adding Phase 3B simulator or evaluation code.

## Existing protections that passed inspection

- `split_dataset` assigns complete pump groups to train, validation, and test. Rolling features are computed by pump, and a pump cannot contribute overlapping windows to multiple splits.
- The MLP and sklearn pipelines fit their imputer/scaler on training rows only. MLP checkpoint selection and Logistic Regression/Random Forest comparison use validation balanced accuracy. Test metrics are calculated after selection and are not used to select models.
- `input_feature_names` omits `scenario_label`, `pump_id`, `timestamp`, `operating_mode`, and `feature_warmup`; MLP training now also validates its requested feature list against that allowlist.
- Confusion counts, class precision/recall/F1, accuracy, balanced accuracy, and multiclass one-vs-rest ROC-AUC are computed from labels/scores in the declared class order. Balanced accuracy averages recall over classes present in `y_true`; macro metrics use the declared class list.

## Weaknesses to address

- The Phase 2/3A dataset generator emits each scenario in the same fixed order for every pump. Although time is not an input, rolling, delta, and lag features can expose scenario transitions and block position. The existing test score therefore does not independently demonstrate robustness to changed scenario order.
- The Phase 3A `operating_variation` offset is a deterministic function of pump index and is applied after `TelemetryReading` validation. It can confound chronological group assignment with sensor baselines, and the adjusted values are not schema-checked again.
- Existing simulation has configurable noise but no explicit temperature/vibration/RPM baseline, fault-strength, or within-run drift settings. It does not simulate sensor dropout; raw CSV ingestion intentionally rejects missing required readings even though model preprocessing can impute feature-level missing values.
- The 3A report evaluates one synthetic distribution. Its probability outputs are classifier scores, not calibrated equipment-failure probabilities. There is no uncertainty response or group-level uncertainty interval.
- The rank-based binary ROC-AUC handles ties, but the average-precision helper processes tied scores one row at a time. That can make binary PR-AUC depend on input ordering for tied scores; Phase 3A's five-class reports do not calculate PR-AUC, but the helper should still be corrected and covered.

Phase 3B will address these issues with randomized per-pump scenario order, configurable condition shifts, a separate validation-selected confidence flag, pump-cluster bootstrap intervals, and deterministic metric/split tests. Results remain synthetic distribution-shift experiments, not real-world validation.
