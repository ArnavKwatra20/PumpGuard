# PumpGuard ACTIII — Focused ML Evaluation

## Scope and inference path

The application does not currently call the trained PyTorch classifier. The simulation endpoint returns the selected synthetic scenario label and invokes the deterministic assess_reading health engine; SavedClassifier is used only by offline scripts. These results evaluate the offline scenario classifier, not the dashboard live inference path. Rule-based health assessment, scenario labels, and the optional diagnostic-explanation provider remain separate.

## Audit

- Target: five-way scenario_label classification (normal, overheating, bearing_wear, cavitation, imbalance). This is synthetic scenario recognition, not prediction of a future failure.
- Features: 32 raw/causal sensor features from input_feature_names; labels, pump IDs, timestamps, operating mode and warm-up metadata are excluded. Training validates features against this allowlist.
- Split/leakage: seed 2027; chronological whole-pump grouping, 12 train / 4 validation / 4 holdout pumps (1,200 / 400 / 400 rows). Causal rolling features are computed per pump; each pump and its overlapping windows stay entirely in one split. Selection uses validation only; holdout metrics do not select weights or thresholds.
- Preprocessing: MLP standardizer and sklearn imputer/scaler are fitted on training rows only.
- Pump identity and timestamps are excluded from features. Within each synthetic pump sequence, scenario order is randomized but labels occur in contiguous segments. Temporal regularities therefore remain simulator-generated and do not establish naturally evolving fault performance.
- Metrics use fixed five-class order; confusion-matrix rows are actual labels and columns predicted labels. Per-class metrics are calculated from these counts. Each condition has 80 samples per class; all sets are balanced by construction.
- All data is synthetic output from hand-authored formulas. More rows do not make it representative of industrial pumps.

## Dataset and commands

Source: generate_condition_rows in src/pumpguard/simulator/robustness.py, SimulatorConditions and the seeded telemetry generator. Base experiment: 400 samples per class, 20 synthetic pump IDs, 2,000 rows total. Defaults: noise 1.0, temperature baseline 68 °C, vibration baseline 2.1 mm/s, sound 68 dB, RPM 1,780, fault intensity 1.0, zero drift. Each shifted condition uses four separate shift pump IDs and 400 evaluation rows.

PowerShell commands:

    $env:PYTHONPATH = 'src'
    .\.venv\Scripts\python.exe scripts/run_robustness.py --seed 2027 --samples-per-scenario 400 --epochs 30 --bootstrap-repetitions 200 --output-json data/reports/phase4_ml_evaluation.json --output-markdown data/reports/phase4_ml_evaluation_runner.md --artifact models/phase4_ml_evaluation_mlp.pt
    .\.venv\Scripts\python.exe -m pytest tests/test_ml_pipeline.py tests/test_robustness.py tests/test_evaluation_quality.py -q

Logistic Regression and Random Forest use existing fixed settings. MLP uses 32 features, 64/32 hidden units, batch size 64, learning rate 0.001, seed 2027, validation balanced accuracy with validation loss tie-break and early stopping. Validation alone selects the MLP checkpoint and uncertainty cutoff.

## Aggregate results

Each condition has 400 synthetic holdout rows (80 per class). CPU times are wall-clock measurements from this run; inference time is the measured 400-row scoring duration divided by 400. MLP has 4,357 trainable parameters. Sizes are serialized model bytes (the sklearn pipeline pickle or PyTorch artifact). Full confusion matrices and per-class metrics are in the machine-readable JSON report.

| Condition | Model | Accuracy | Balanced acc. | Macro P | Macro R | Macro F1 | CPU fit s | Inference ms/row | Size bytes | Parameters | High-score errors ≥0.90 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| In-distribution pump holdout | Logistic Regression | 0.990 | 0.990 | 0.990 | 0.990 | 0.990 | 0.0421 | 0.02385 | 3934 | — | 1 |
| In-distribution pump holdout | Random Forest | 0.990 | 0.990 | 0.990 | 0.990 | 0.990 | 0.2400 | 0.04045 | 574239 | — | 0 |
| In-distribution pump holdout | PyTorch MLP | 0.983 | 0.982 | 0.983 | 0.982 | 0.983 | 0.7872 | 0.00940 | 25505 | 4,357 | 2 |
| Unseen pump configuration + baseline/drift shift | Logistic Regression | 0.207 | 0.208 | 0.440 | 0.208 | 0.082 | 0.0421 | 0.02164 | 3934 | — | 307 |
| Unseen pump configuration + baseline/drift shift | Random Forest | 0.948 | 0.948 | 0.951 | 0.948 | 0.947 | 0.2400 | 0.04016 | 574239 | — | 0 |
| Unseen pump configuration + baseline/drift shift | PyTorch MLP | 0.207 | 0.208 | 0.240 | 0.208 | 0.082 | 0.7872 | 0.01006 | 25505 | 4,357 | 295 |
| Increased sensor noise (2x) | Logistic Regression | 0.917 | 0.918 | 0.919 | 0.918 | 0.917 | 0.0421 | 0.02198 | 3934 | — | 13 |
| Increased sensor noise (2x) | Random Forest | 0.940 | 0.940 | 0.940 | 0.940 | 0.939 | 0.2400 | 0.03966 | 574239 | — | 0 |
| Increased sensor noise (2x) | PyTorch MLP | 0.880 | 0.880 | 0.880 | 0.880 | 0.878 | 0.7872 | 0.00913 | 25505 | 4,357 | 16 |
| Weaker fault signatures (0.55x) | Logistic Regression | 0.725 | 0.725 | 0.811 | 0.725 | 0.733 | 0.0421 | 0.02269 | 3934 | — | 9 |
| Weaker fault signatures (0.55x) | Random Forest | 0.705 | 0.705 | 0.792 | 0.705 | 0.707 | 0.2400 | 0.04008 | 574239 | — | 0 |
| Weaker fault signatures (0.55x) | PyTorch MLP | 0.815 | 0.815 | 0.861 | 0.815 | 0.810 | 0.7872 | 0.00989 | 25505 | 4,357 | 8 |
| 5% sensor dropout | Logistic Regression | 0.998 | 0.997 | 0.998 | 0.997 | 0.997 | 0.0421 | 0.02262 | 3934 | — | 1 |
| 5% sensor dropout | Random Forest | 0.995 | 0.995 | 0.995 | 0.995 | 0.995 | 0.2400 | 0.04108 | 574239 | — | 0 |
| 5% sensor dropout | PyTorch MLP | 0.998 | 0.997 | 0.998 | 0.997 | 0.997 | 0.7872 | 0.01103 | 25505 | 4,357 | 1 |

## Confidence and cluster-level uncertainty

Maximum class scores are uncalibrated classifier scores, not probabilities of failure. The reject threshold is selected only from validation rows. Bootstrap intervals resample complete pump groups, not individual sensor rows; with four holdout pumps they are coarse.

| Condition | Model | Score p10 / p50 / p90 | Validation cutoff | Holdout uncertain rate | Macro-F1 pump-bootstrap 95% interval |
|---|---|---:|---:|---:|---:|
| In-distribution | Logistic Regression | 0.928 / 0.998 / 1.000 | 0.525 | 0.003 | [0.982, 0.997] |
| In-distribution | Random Forest | 0.873 / 0.990 / 1.000 | 0.310 | 0.000 | [0.990, 0.990] |
| In-distribution | PyTorch MLP | 0.948 / 0.999 / 1.000 | 0.502 | 0.003 | [0.970, 0.995] |
| Baseline/drift shift | Logistic Regression | 0.997 / 1.000 / 1.000 | 0.525 | 0.003 | [0.072, 0.087] |
| Baseline/drift shift | Random Forest | 0.456 / 0.663 / 0.897 | 0.310 | 0.010 | [0.931, 0.967] |
| Baseline/drift shift | PyTorch MLP | 0.954 / 1.000 / 1.000 | 0.502 | 0.000 | [0.072, 0.100] |
| 2x sensor noise | Logistic Regression | 0.723 / 0.994 / 1.000 | 0.525 | 0.020 | [0.900, 0.932] |
| 2x sensor noise | Random Forest | 0.548 / 0.868 / 0.981 | 0.310 | 0.003 | [0.929, 0.949] |
| 2x sensor noise | PyTorch MLP | 0.788 / 0.995 / 1.000 | 0.502 | 0.025 | [0.871, 0.886] |
| Weak fault signatures | Logistic Regression | 0.518 / 0.799 / 0.997 | 0.525 | 0.110 | [0.679, 0.765] |
| Weak fault signatures | Random Forest | 0.327 / 0.523 / 0.990 | 0.310 | 0.045 | [0.623, 0.775] |
| Weak fault signatures | PyTorch MLP | 0.543 / 0.910 / 0.999 | 0.502 | 0.048 | [0.792, 0.835] |
| 5% feature dropout | Logistic Regression | 0.961 / 0.998 / 1.000 | 0.525 | 0.005 | [0.992, 1.000] |
| 5% feature dropout | Random Forest | 0.857 / 0.990 / 1.000 | 0.310 | 0.000 | [0.990, 1.000] |
| 5% feature dropout | PyTorch MLP | 0.966 / 0.999 / 1.000 | 0.502 | 0.000 | [0.992, 1.000] |

## Per-class precision / recall / F1

### In-distribution pump holdout

| Model | Class | Precision | Recall | F1 | Support |
|---|---|---:|---:|---:|---:|
| Logistic Regression | normal | 1.000 | 1.000 | 1.000 | 80 |
| Logistic Regression | overheating | 1.000 | 1.000 | 1.000 | 80 |
| Logistic Regression | bearing_wear | 0.975 | 0.975 | 0.975 | 80 |
| Logistic Regression | cavitation | 0.976 | 1.000 | 0.988 | 80 |
| Logistic Regression | imbalance | 1.000 | 0.975 | 0.987 | 80 |
| Random Forest | normal | 1.000 | 1.000 | 1.000 | 80 |
| Random Forest | overheating | 1.000 | 1.000 | 1.000 | 80 |
| Random Forest | bearing_wear | 0.987 | 0.963 | 0.975 | 80 |
| Random Forest | cavitation | 0.976 | 1.000 | 0.988 | 80 |
| Random Forest | imbalance | 0.988 | 0.988 | 0.988 | 80 |
| PyTorch MLP | normal | 1.000 | 1.000 | 1.000 | 80 |
| PyTorch MLP | overheating | 1.000 | 1.000 | 1.000 | 80 |
| PyTorch MLP | bearing_wear | 0.962 | 0.950 | 0.956 | 80 |
| PyTorch MLP | cavitation | 0.952 | 0.988 | 0.969 | 80 |
| PyTorch MLP | imbalance | 1.000 | 0.975 | 0.987 | 80 |

### Unseen pump configuration + baseline/drift shift

| Model | Class | Precision | Recall | F1 | Support |
|---|---|---:|---:|---:|---:|
| Logistic Regression | normal | 0.000 | 0.000 | 0.000 | 80 |
| Logistic Regression | overheating | 1.000 | 0.013 | 0.025 | 80 |
| Logistic Regression | bearing_wear | 0.000 | 0.000 | 0.000 | 80 |
| Logistic Regression | cavitation | 0.202 | 1.000 | 0.335 | 80 |
| Logistic Regression | imbalance | 1.000 | 0.025 | 0.049 | 80 |
| Random Forest | normal | 1.000 | 0.900 | 0.947 | 80 |
| Random Forest | overheating | 0.920 | 1.000 | 0.958 | 80 |
| Random Forest | bearing_wear | 0.986 | 0.863 | 0.920 | 80 |
| Random Forest | cavitation | 0.919 | 0.988 | 0.952 | 80 |
| Random Forest | imbalance | 0.929 | 0.988 | 0.958 | 80 |
| PyTorch MLP | normal | 0.000 | 0.000 | 0.000 | 80 |
| PyTorch MLP | overheating | 1.000 | 0.037 | 0.072 | 80 |
| PyTorch MLP | bearing_wear | 0.000 | 0.000 | 0.000 | 80 |
| PyTorch MLP | cavitation | 0.202 | 1.000 | 0.335 | 80 |
| PyTorch MLP | imbalance | 0.000 | 0.000 | 0.000 | 80 |

### Increased sensor noise (2x)

| Model | Class | Precision | Recall | F1 | Support |
|---|---|---:|---:|---:|---:|
| Logistic Regression | normal | 0.974 | 0.950 | 0.962 | 80 |
| Logistic Regression | overheating | 1.000 | 0.963 | 0.981 | 80 |
| Logistic Regression | bearing_wear | 0.863 | 0.787 | 0.824 | 80 |
| Logistic Regression | cavitation | 0.886 | 0.975 | 0.929 | 80 |
| Logistic Regression | imbalance | 0.869 | 0.912 | 0.890 | 80 |
| Random Forest | normal | 0.988 | 1.000 | 0.994 | 80 |
| Random Forest | overheating | 1.000 | 1.000 | 1.000 | 80 |
| Random Forest | bearing_wear | 0.878 | 0.812 | 0.844 | 80 |
| Random Forest | cavitation | 0.951 | 0.963 | 0.957 | 80 |
| Random Forest | imbalance | 0.881 | 0.925 | 0.902 | 80 |
| PyTorch MLP | normal | 0.962 | 0.938 | 0.949 | 80 |
| PyTorch MLP | overheating | 1.000 | 0.963 | 0.981 | 80 |
| PyTorch MLP | bearing_wear | 0.786 | 0.688 | 0.733 | 80 |
| PyTorch MLP | cavitation | 0.840 | 0.988 | 0.908 | 80 |
| PyTorch MLP | imbalance | 0.815 | 0.825 | 0.820 | 80 |

### Weaker fault signatures (0.55x)

| Model | Class | Precision | Recall | F1 | Support |
|---|---|---:|---:|---:|---:|
| Logistic Regression | normal | 0.533 | 1.000 | 0.696 | 80 |
| Logistic Regression | overheating | 1.000 | 0.713 | 0.832 | 80 |
| Logistic Regression | bearing_wear | 0.580 | 0.637 | 0.607 | 80 |
| Logistic Regression | cavitation | 0.967 | 0.725 | 0.829 | 80 |
| Logistic Regression | imbalance | 0.978 | 0.550 | 0.704 | 80 |
| Random Forest | normal | 0.523 | 1.000 | 0.687 | 80 |
| Random Forest | overheating | 1.000 | 0.713 | 0.832 | 80 |
| Random Forest | bearing_wear | 0.568 | 0.625 | 0.595 | 80 |
| Random Forest | cavitation | 0.924 | 0.762 | 0.836 | 80 |
| Random Forest | imbalance | 0.944 | 0.425 | 0.586 | 80 |
| PyTorch MLP | normal | 0.584 | 1.000 | 0.737 | 80 |
| PyTorch MLP | overheating | 1.000 | 0.887 | 0.940 | 80 |
| PyTorch MLP | bearing_wear | 0.872 | 0.425 | 0.571 | 80 |
| PyTorch MLP | cavitation | 0.890 | 0.912 | 0.901 | 80 |
| PyTorch MLP | imbalance | 0.958 | 0.850 | 0.901 | 80 |

### 5% sensor dropout

| Model | Class | Precision | Recall | F1 | Support |
|---|---|---:|---:|---:|---:|
| Logistic Regression | normal | 1.000 | 1.000 | 1.000 | 80 |
| Logistic Regression | overheating | 1.000 | 1.000 | 1.000 | 80 |
| Logistic Regression | bearing_wear | 0.988 | 1.000 | 0.994 | 80 |
| Logistic Regression | cavitation | 1.000 | 1.000 | 1.000 | 80 |
| Logistic Regression | imbalance | 1.000 | 0.988 | 0.994 | 80 |
| Random Forest | normal | 0.988 | 1.000 | 0.994 | 80 |
| Random Forest | overheating | 1.000 | 1.000 | 1.000 | 80 |
| Random Forest | bearing_wear | 1.000 | 0.988 | 0.994 | 80 |
| Random Forest | cavitation | 1.000 | 1.000 | 1.000 | 80 |
| Random Forest | imbalance | 0.988 | 0.988 | 0.988 | 80 |
| PyTorch MLP | normal | 1.000 | 1.000 | 1.000 | 80 |
| PyTorch MLP | overheating | 1.000 | 1.000 | 1.000 | 80 |
| PyTorch MLP | bearing_wear | 0.988 | 1.000 | 0.994 | 80 |
| PyTorch MLP | cavitation | 1.000 | 1.000 | 1.000 | 80 |
| PyTorch MLP | imbalance | 1.000 | 0.988 | 0.994 | 80 |

## Key confusion matrices

Matrix row/column order: normal, overheating, bearing_wear, cavitation, imbalance. The JSON report contains matrices for every model and condition.

### In-distribution pump holdout

- Logistic Regression: [[80,0,0,0,0],[0,80,0,0,0],[0,0,78,2,0],[0,0,0,80,0],[0,0,2,0,78]]
- Random Forest: [[80,0,0,0,0],[0,80,0,0,0],[0,0,77,2,1],[0,0,0,80,0],[0,0,1,0,79]]
- PyTorch MLP: [[80,0,0,0,0],[0,80,0,0,0],[0,0,76,4,0],[0,0,1,79,0],[0,0,2,0,78]]

### Unseen pump configuration + baseline/drift shift

- Logistic Regression: [[0,0,0,80,0],[0,1,0,79,0],[0,0,0,80,0],[0,0,0,80,0],[0,0,0,78,2]]
- Random Forest: [[72,7,0,1,0],[0,80,0,0,0],[0,0,69,5,6],[0,0,1,79,0],[0,0,0,1,79]]
- PyTorch MLP: [[0,0,0,80,0],[0,3,0,77,0],[0,0,0,80,0],[0,0,0,80,0],[0,0,0,80,0]]

### Weaker fault signatures (0.55x)

- Logistic Regression: [[80,0,0,0,0],[23,57,0,0,0],[26,0,51,2,1],[7,0,15,58,0],[14,0,22,0,44]]
- Random Forest: [[80,0,0,0,0],[23,57,0,0,0],[23,0,50,5,2],[6,0,13,61,0],[21,0,25,0,34]]
- PyTorch MLP: [[80,0,0,0,0],[9,71,0,0,0],[34,0,34,9,3],[4,0,3,73,0],[10,0,2,0,68]]

## Findings and improvement decision

- In-distribution macro F1 is 0.990 for Logistic Regression and Random Forest and 0.983 for the MLP. Errors mainly involve bearing wear versus cavitation or imbalance.
- Highest-impact weakness: under the unseen baseline (76 °C, 2.8 mm/s vibration, 1,680 RPM) plus gradual temperature/vibration/RPM drift, the MLP predicts cavitation for most classes. Its macro F1 drops to 0.082; class recalls are normal 0.000, overheating 0.038, bearing_wear 0.000, cavitation 1.000 and imbalance 0.000. Logistic Regression has the same collapse (macro F1 0.082). Random Forest scores 0.947 macro F1 on this one synthetic configuration; that does not establish general robustness.
- At weaker fault intensity, MLP macro F1 is 0.810 and bearing-wear recall is 0.425; 34/80 bearing-wear samples were called normal. This matches overlap introduced by the simulator's reduced fault offsets.
- At 2x noise, MLP macro F1 is 0.878 and bearing-wear recall is 0.688. The scripted 5% feature dropout condition remained easy for all three models and is only a narrow software check.
- Confidence fails as a shift warning: the MLP's shifted-set median maximum score is near 1.0; 295/400 shifted MLP predictions are wrong at score ≥0.90, while the validation-selected cutoff flags none. These scores are not calibrated probabilities of correctness or failure.
- False positives under baseline/drift shift: both LR and MLP label all 80 normal holdout rows cavitation. RF labels 7/80 normal rows overheating. Under weak signatures, normal is also a common prediction for fault classes.

No model or inference behavior was changed. The shift failure is clear, but these synthetic tests do not justify changing production model selection, thresholds or adding an OOD gate. Choosing Random Forest from this final holdout would be test-set selection. A justified change needs representative operating envelopes and a separate independent validation set. The current dashboard health engine remains deterministic and separate from this offline classifier.

## Verification and limitations

- The CPU experiment completed and generated data/reports/phase4_ml_evaluation.json, data/reports/phase4_ml_evaluation_runner.md and models/phase4_ml_evaluation_mlp.pt. The focused Markdown report here was written from those outputs.
- Focused tests: 19 passed (test_ml_pipeline.py, test_robustness.py, test_evaluation_quality.py).
- No application code changed; no frontend build or unrelated full suite was run.
- Rows are correlated. Existing bootstrap resamples pump clusters rather than rows, but four test pumps make intervals coarse; shift sets also use four synthetic pump IDs.
- There are no field histories, confirmed maintenance outcomes, failure horizons or real assets. No industrial accuracy, calibrated risk, predictive-maintenance performance or early-warning lead time is established.
- No cloud provisioning, AMD GPU training or GPU benchmarks were attempted.
