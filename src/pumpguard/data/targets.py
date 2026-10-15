"""Honest target definitions for later supervised experiments."""
TARGET_DEFINITIONS = {
    "scenario_classification": {
        "target": "scenario_label",
        "meaning": "Identify which controlled synthetic operating scenario generated a reading.",
        "validity": "Scenario label is simulator ground truth, not a failure event.",
    },
    "anomaly_detection": {
        "target": None,
        "meaning": "Flag deviations from a stated baseline using rules or an unsupervised detector.",
        "validity": "Anomaly status is not a future-failure label.",
    },
    "predictive_maintenance": {
        "target": None,
        "meaning": "Predict a future event within a defined horizon from prior history.",
        "validity": "Not supported until real or appropriately defined future-event labels exist.",
    },
}
LABEL_COLUMNS = frozenset({"scenario_label", "target", "failure_label", "future_event", "event_time"})
