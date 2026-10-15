# PumpGuard Phase 3B — Synthetic Robustness Results

Run seed: 2027. Training used 1200 rows; validation 400; standard holdout 400. Whole pump groups were kept disjoint.

All generated records and condition shifts are synthetic. These results are software robustness checks, not real-world validation or predictive-maintenance evidence.

## Results

| Evaluation condition | Model | Accuracy | Balanced accuracy | Macro precision | Macro recall | Macro F1 | F1 95% pump-bootstrap interval | CPU train s | Mean batched inference ms/row | Serialized model bytes |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| in_distribution | logistic_regression | 0.990 | 0.990 | 0.990 | 0.990 | 0.990 | [0.982, 0.997] | 0.0764 | 0.0243 | 3934 |
| in_distribution | random_forest | 0.990 | 0.990 | 0.990 | 0.990 | 0.990 | [0.990, 0.990] | 0.3904 | 0.0504 | 574239 |
| in_distribution | pytorch_mlp | 0.983 | 0.982 | 0.983 | 0.982 | 0.983 | [0.970, 0.995] | 1.0013 | 0.0095 | 25221 |
| unseen_pump_configuration_and_drift | logistic_regression | 0.207 | 0.208 | 0.440 | 0.208 | 0.082 | [0.072, 0.087] | 0.0764 | 0.0246 | 3934 |
| unseen_pump_configuration_and_drift | random_forest | 0.948 | 0.948 | 0.951 | 0.948 | 0.947 | [0.931, 0.970] | 0.3904 | 0.0499 | 574239 |
| unseen_pump_configuration_and_drift | pytorch_mlp | 0.207 | 0.208 | 0.240 | 0.208 | 0.082 | [0.067, 0.095] | 1.0013 | 0.0104 | 25221 |
| increased_sensor_noise | logistic_regression | 0.917 | 0.918 | 0.919 | 0.918 | 0.917 | [0.900, 0.935] | 0.0764 | 0.0282 | 3934 |
| increased_sensor_noise | random_forest | 0.940 | 0.940 | 0.940 | 0.940 | 0.939 | [0.929, 0.949] | 0.3904 | 0.0498 | 574239 |
| increased_sensor_noise | pytorch_mlp | 0.880 | 0.880 | 0.880 | 0.880 | 0.878 | [0.871, 0.886] | 1.0013 | 0.0118 | 25221 |
| weaker_fault_signatures | logistic_regression | 0.725 | 0.725 | 0.811 | 0.725 | 0.733 | [0.679, 0.765] | 0.0764 | 0.0277 | 3934 |
| weaker_fault_signatures | random_forest | 0.705 | 0.705 | 0.792 | 0.705 | 0.707 | [0.636, 0.775] | 0.3904 | 0.0716 | 574239 |
| weaker_fault_signatures | pytorch_mlp | 0.815 | 0.815 | 0.861 | 0.815 | 0.810 | [0.792, 0.835] | 1.0013 | 0.0147 | 25221 |
| sensor_dropout_5pct | logistic_regression | 0.998 | 0.997 | 0.998 | 0.997 | 0.997 | [0.992, 1.000] | 0.0764 | 0.0260 | 3934 |
| sensor_dropout_5pct | random_forest | 0.995 | 0.995 | 0.995 | 0.995 | 0.995 | [0.990, 1.000] | 0.3904 | 0.0508 | 574239 |
| sensor_dropout_5pct | pytorch_mlp | 0.998 | 0.997 | 0.998 | 0.997 | 0.997 | [0.992, 1.000] | 1.0013 | 0.0137 | 25221 |

## Observed failure modes

- in_distribution, logistic_regression: bearing_wear → cavitation (2), imbalance → bearing_wear (2).
- in_distribution, random_forest: bearing_wear → cavitation (2), bearing_wear → imbalance (1), imbalance → bearing_wear (1).
- in_distribution, pytorch_mlp: bearing_wear → cavitation (4), imbalance → bearing_wear (2), cavitation → bearing_wear (1).
- unseen_pump_configuration_and_drift, logistic_regression: bearing_wear → cavitation (80), normal → cavitation (80), overheating → cavitation (79).
- unseen_pump_configuration_and_drift, random_forest: normal → overheating (7), bearing_wear → imbalance (6), bearing_wear → cavitation (5).
- unseen_pump_configuration_and_drift, pytorch_mlp: bearing_wear → cavitation (80), imbalance → cavitation (80), normal → cavitation (80).
- increased_sensor_noise, logistic_regression: bearing_wear → imbalance (11), imbalance → bearing_wear (7), bearing_wear → cavitation (5).
- increased_sensor_noise, random_forest: bearing_wear → imbalance (10), imbalance → bearing_wear (6), bearing_wear → cavitation (4).
- increased_sensor_noise, pytorch_mlp: bearing_wear → imbalance (15), imbalance → bearing_wear (12), bearing_wear → cavitation (10).
- weaker_fault_signatures, logistic_regression: bearing_wear → normal (26), overheating → normal (23), imbalance → bearing_wear (22).
- weaker_fault_signatures, random_forest: imbalance → bearing_wear (25), bearing_wear → normal (23), overheating → normal (23).
- weaker_fault_signatures, pytorch_mlp: bearing_wear → normal (34), imbalance → normal (10), bearing_wear → cavitation (9).
- sensor_dropout_5pct, logistic_regression: imbalance → bearing_wear (1).
- sensor_dropout_5pct, random_forest: bearing_wear → imbalance (1), imbalance → normal (1).
- sensor_dropout_5pct, pytorch_mlp: imbalance → bearing_wear (1).

Across this simulator, bearing-wear and cavitation signatures both raise vibration and sound, so those classes are repeatedly confused. With weaker faults, several models confuse fault classes with normal because the simulated offsets approach the normal sensor distribution. Under the shifted temperature/vibration/RPM baseline, Logistic Regression and the MLP collapse toward cavitation while the Random Forest remains stronger on this particular generated configuration. These are observations consistent with the hand-authored signal formulas, not a causal diagnosis of real equipment.

Validation-selected score cutoffs did not detect this shift reliably (logistic_regression: uncertain 1/400, high-confidence errors 307; random_forest: uncertain 4/400, high-confidence errors 0; pytorch_mlp: uncertain 0/400, high-confidence errors 295).

## Confidence and limitations

Validation-only reject cutoffs aim for at most 5% empirical error while retaining at least 50% validation coverage. The same cutoff is applied to every holdout condition. It is an empirical uncertain-prediction flag, not calibrated confidence or a failure probability. High-confidence errors and coverage are included in the JSON report.

Intervals resample complete pump groups, not individual sensor rows. Each evaluation condition has four held-out pump groups, so the bootstrap intervals are coarse and flagged as small-cluster estimates. Simulator patterns, fixed schema, chosen condition ranges, and small pump counts do not establish generalization to industrial equipment. Rule-based health assessment remains independent of scenario classification.

The report does not select a model or tune a threshold from final holdout metrics. Logistic Regression and Random Forest use fixed Phase 2 settings; the MLP checkpoint and each reject threshold use validation only.
