# AMD compute and predictive-maintenance status

## Separate AMD capabilities

AMD Token Factory is the hosted LLM API configured by `RADEON_BASE_URL`, `RADEON_API_KEY`, and `RADEON_MODEL`. It does not imply that PumpGuard has access to an AMD GPU. The AMD model API documents `GET /v1/models` as a dynamic catalog that carries model IDs, supported parameters, modalities, JSON-output support, and provider capability flags, and `POST /v1/chat/completions` as the inference path. PumpGuard reads those catalog fields at runtime and caches them in memory for three minutes. The API layer exposes only fields actually returned by AMD.

## GPU suitability and boundary

PyTorch training and inference use `pumpguard.ml.compute` as the provider boundary. `auto` selects AMD ROCm only when the installed PyTorch build reports HIP, a device is available, and visible device names identify AMD/Radeon/Instinct; otherwise it chooses CPU. Explicit `amd-rocm` refuses to fall back. The legacy explicit `cuda` choice remains available for callers that already used it, but it is reported as AMD ROCm only when runtime checks prove that.

The existing scenario MLP is a small dense classifier and is the current target for GPU acceleration. It uses the same split, preprocessing, seed, labels, and metrics on CPU and GPU; it records the selected provider, device, model version, training settings, and inference path. Run `python scripts/benchmark_compute.py` in a compatible AMD environment to create a reproducible CPU-versus-AMD report. Without a detected AMD GPU the report records the GPU run as unavailable and retains the measured CPU result.

The scalar seeded simulator generates a few readings per request and calls Python/NumPy random sampling per reading. Moving that path to GPU would add transfer/kernel overhead and risk changing reproducible seeded output. Rolling telemetry features currently cover four channels and short windows (three and five samples); these operations are small CPU-bound loops. No GPU path was added for either workload, and there is no CPU-versus-GPU performance claim for them. A future large-batch/vectorized workload should be measured before adding a separate accelerator implementation.

## Predictive tasks the current labels support

`scripts/evaluate_predictive_maintenance.py` evaluates binary normal-versus-threshold-anomaly detection from the deterministic health rules and, when a compatible saved artifact is available, scenario classification on the existing group holdout. Results are explicitly marked synthetic. It reports fault co-occurrence only; the simulator's scenario labels do not establish causal propagation or component root cause.

The current telemetry dataset contains no measured degradation paths to a failure boundary, run-to-failure durations, censoring, or remaining-life labels. Degradation forecasting and remaining-useful-life metrics are therefore marked not evaluable instead of inferred from scenario labels. The diagnostic explanation layer validates evidence references against supplied telemetry, health assessment, and optional classifier output. Its ranked causes remain hypotheses requiring human review.

## Verification state and GPU setup

On the development machine checked for this implementation, PyTorch is a CPU build (`2.7.1+cpu`), reports no HIP runtime, and exposes no accelerator. The CPU path is testable here; AMD GPU training/inference remains pending compatible infrastructure access.

In an AMD GPU environment:

1. Install the PyTorch/ROCm build supported by the selected AMD instance and its operating system using AMD's current ROCm installation guidance; do not install a CUDA wheel and assume it is ROCm.
2. Copy or generate the synthetic training CSV and verify the runtime with `python scripts/verify_gpu.py`. Continue only when it reports `provider: amd_rocm` and `intended_amd_gpu_accessible: true`.
3. Run `python scripts/train_cloud.py --input data/raw/pump_telemetry.csv --artifact models/pumpguard_mlp_amd.pt --seed 42 --epochs 40 --batch-size 64 --learning-rate 0.001 --patience 6`. This entry point fails before training if a compatible AMD ROCm device is absent.
4. Run `python scripts/benchmark_compute.py --input data/raw/pump_telemetry.csv --seed 42 --epochs 40 --batch-size 64 --learning-rate 0.001 --patience 6 --output data/reports/compute_benchmark.json` to record both paths and their test metrics when AMD is visible.
5. Set `PUMPGUARD_ML_ARTIFACT` to the trained artifact and `PUMPGUARD_COMPUTE_PROVIDER=amd-rocm` for the API process. `/api/v1/ml/status` and the Diagnostic Inspector report the actual provider, device, model version, and execution path. The CPU path remains the default fallback only when provider is `auto`.

These steps do not change Token Factory credentials or establish real-world predictive-maintenance validity.
