# PumpGuard Phase 3A — Local ML Results

## Experiment configuration

- Data: 1,500 generated synthetic records; five scenario classes, 300 each.
- Pump groups: 10; train groups pump-01 through pump-06, validation pump-07 and pump-08, test pump-09 and pump-10.
- Split counts: 900 train, 300 validation, 300 test. Complete pump histories stay in one split.
- Generator settings: seed 2026, simulator noise scale 1.5, pump operating variation 1.0.
- Features: Phase 2 causal feature pipeline and allowlist; 32 ordered numeric features. IDs, timestamp, operating mode, label, and warm-up flag are not inputs.
- Preprocessing: median imputation and standardization fitted on the 900 training rows only.
- PyTorch: 2.7.1+cpu on Windows 11, CPU-only; MLP 64/32 hidden units, 4,357 trainable parameters, batch size 64, learning rate 0.001, 20 epochs, seed 2026. Validation balanced accuracy selected the checkpoint; best epoch was 20.
- Baselines: existing scikit-learn Logistic Regression and Random Forest (100 trees), same groups, rows, feature order, and seed. Each model was scored on test only after validation-based selection; test results below are descriptive and did not select a model.

## Measured results

| Model | Validation balanced accuracy | Test accuracy | Test balanced accuracy | Test macro F1 | CPU fit time | Test inference time |
|---|---:|---:|---:|---:|---:|---:|
| Logistic Regression | 0.9833 | 0.9900 | 0.9900 | 0.9900 | 0.071 s | 0.0067 s |
| Random Forest | 0.9667 | 0.9100 | 0.9100 | 0.9085 | 0.190 s | 0.0124 s |
| PyTorch MLP | 0.9633 | 0.9767 | 0.9767 | 0.9768 | 0.436 s | 0.0026 s |

Per-class metrics, confusion matrices, full precision timing, and artifact metadata are in `data/reports/model_comparison_phase3a.json` (generated report; ignored by Git). The saved model artifact is `models/pumpguard_mlp.pt` (also generated/ignored).

These values describe this deterministic synthetic simulator experiment only. They are not evidence about real industrial pump operation. Logistic Regression had the strongest validation score and was selected by the existing baseline procedure; its test score was measured afterward. The MLP's test score happened to be higher than the Random Forest's, while Logistic Regression remained stronger. The dataset has ten synthetic pump identities and hand-authored scenario patterns, so performance on held-out synthetic pumps does not establish generalization to real machines.

## Device check and verification

`scripts/verify_gpu.py` reported PyTorch 2.7.1+cpu, Windows 11, no available device, and `intended_amd_gpu_accessible: false`. No GPU or cloud training was performed. The standard suite completed with 37 tests passing after Phase 3A changes; one existing Starlette/httpx deprecation warning remains.
