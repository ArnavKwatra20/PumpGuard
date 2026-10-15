# PumpGuard architecture

## Phase 1 runtime flow

A request to the FastAPI simulation route validates scenario parameters, asks the seeded simulator for synthetic readings, stores only telemetry in a bounded process-local service, and assesses the newest reading. The scenario ground-truth label is returned separately and is not a telemetry model field. The health service calls framework-independent threshold rules and emits explainable anomalies, pattern indicators, a deterministic score, and recommendations.

The API history is lost on process restart. No database, background simulation, trained model, LLM, or external service is involved.

## Phase 2 data flow

```text
seed + fixed start time
        |
        v
scripts/generate_dataset.py ---> data/raw/pump_telemetry.csv
                                      |
                       strict schema, finite numeric, ordering,
                       duplicate-key, and label validation
                                      |
                                      v
                         causal per-pump feature engineering
                                      |
                                      v
                   data/processed/pump_features.csv
                      |            |             |
                      v            v             v
                   quality      grouped       CPU baseline
                   report       time splits   experiments
```

Raw data and derived features use separate directories. The raw schema remains compatible with Phase 1 CSV fields. Feature engineering retains original columns and adds trailing means/stddevs, previous-step deltas, relative changes, lags, and an explicit warm-up marker. Calculation sorts by pump and timestamp, resets all rolling state at pump boundaries, and reads no future values.

## Component responsibilities

- `pumpguard.data.pipeline`: required-column checks, timestamp parsing, Pydantic sensor validation, label validation, chronology and duplicate detection, CSV I/O.
- `pumpguard.data.features`: configurable causal temporal features; blank warm-up values and dimensionless relative changes.
- `pumpguard.data.splitting`: whole-pump chronological group holdouts and split metadata. Groups never cross train/validation/test.
- `pumpguard.data.targets`: distinction among simulator scenario labels, anomaly detection, and future-event prediction.
- `pumpguard.data.evaluation`: dependency-light classification metrics. ROC-AUC/PR-AUC are emitted only for compatible score shapes and class coverage.
- `pumpguard.data.quality`: synthetic-data quality audit and Markdown formatting.
- `pumpguard.data.preprocessing`: train-only median imputation and standardization for the CPU fallback.
- `scripts/run_baselines.py`: optional scikit-learn Logistic Regression/Random Forest comparison; validation selects, test reports once. It falls back to a small pure-Python nearest-centroid baseline if scikit-learn native libraries are unavailable.
- Existing API, simulator, detection, and service modules remain independent of the optional ML dependency.

## Targets and evaluation boundaries

Scenario classification predicts the controlled synthetic `scenario_label`. That label, pump identifier, timestamp, operating mode, and warm-up marker are excluded from model inputs. This target does not indicate an impending breakdown.

Anomaly detection remains a separate rule-based baseline. Predictive maintenance needs event timestamps or labels and a defined future prediction horizon; neither is available in these synthetic scenario rows. The current pipeline does not create or infer failure labels.

Preprocessing is fitted only with training data. Pump groups and overlapping windows stay within one split. Validation results may select between candidate models. The test group is reserved for final reporting. Current generated groups have separated time blocks; for arbitrary input data, check the saved group time ranges for overlap.

## Synthetic assumptions and future extension

The simulator hard-codes illustrative signal patterns for normal operation, overheating, bearing wear, cavitation, and imbalance. Synthetic scenario classification scores measure only how well a model recovers those simulator patterns. They do not demonstrate reliability on a physical pump.

The future AMD Developer Cloud phase can consume raw or processed CSV with the saved split metadata and reuse the feature functions for CPU or GPU training. GPU training, cloud integration, model serving, and real pump validation are not part of this phase.
