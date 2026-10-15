# Phase 2 target definitions

| Task | Target | What it answers | Phase 2 status |
|---|---|---|---|
| Scenario classification | `scenario_label` | Which controlled synthetic scenario generated this row? | Supported for simulator experiments |
| Anomaly detection | Baseline/rule deviation | Does a reading deviate from an appropriate baseline? | Separate Phase 1 rules baseline |
| Predictive maintenance | Future event within a defined horizon | Will a specified event occur within a horizon using prior history? | Unsupported: no event labels or horizon |

The scenario label is ground truth for simulator generation, not an industrial failure label. The allowlisted model inputs exclude `scenario_label`, `target`, `failure_label`, `future_event`, and `event_time`, as well as pump IDs, timestamps, operating modes, and warm-up indicators. No failure probability or remaining useful life is estimated.
