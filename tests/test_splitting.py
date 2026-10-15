from datetime import datetime, timedelta, timezone
from pumpguard.data.features import engineer_features
from pumpguard.data.preprocessing import TrainingOnlyStandardizer
from pumpguard.data.splitting import input_feature_names, split_dataset
from pumpguard.simulator.generator import SCENARIOS, TelemetryGenerator

def dataset():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index in range(5):
        generator = TelemetryGenerator(50 + index)
        for scenario_index, scenario in enumerate(SCENARIOS):
            readings = generator.generate_sequence(scenario, 6, 1, f"pump-{index}", start + timedelta(seconds=index * 100 + scenario_index * 10))
            for reading, label in readings:
                item = reading.model_dump(mode="python")
                item["scenario_label"] = label
                rows.append(item)
    return engineer_features(rows)

def test_group_splits_are_disjoint_complete_reproducible_and_chronological():
    rows = dataset()
    first, meta1 = split_dataset(rows, seed=9)
    second, meta2 = split_dataset(rows, seed=9)
    groups = [set(meta1["groups"][part]) for part in ("train", "validation", "test")]
    assert meta1 == meta2
    assert not groups[0] & groups[1] and not groups[0] & groups[2] and not groups[1] & groups[2]
    assert set.union(*groups) == {f"pump-{i}" for i in range(5)}
    for part in first.values():
        for pump in {r["pump_id"] for r in part}:
            dates = [r["timestamp"] for r in part if r["pump_id"] == pump]
            assert dates == sorted(dates)
    assert meta1["sample_counts"] == {k: len(v) for k, v in first.items()}
    ranges = [meta1["timestamp_ranges"][name] for name in ("train", "validation", "test")]
    assert ranges[0]["end"] < ranges[1]["start"] < ranges[2]["start"]

def test_label_exclusion_and_feature_presence():
    names = input_feature_names(dataset())
    assert "temperature_c_roll_mean_w3" in names
    assert "scenario_label" not in names and "pump_id" not in names and "timestamp" not in names

def test_preprocessor_fits_training_data_only():
    train = [[1.0, None], [3.0, 4.0], [5.0, 6.0]]
    validation = [[1e12, 1e12]]
    scaler = TrainingOnlyStandardizer().fit(train)
    fitted_means = list(scaler.means_)
    transformed = scaler.transform(validation)
    assert transformed[0][0] > 1e6
    assert scaler.means_ == fitted_means == [3.0, 5.0]

def test_too_few_groups_is_clear():
    try:
        split_dataset(dataset()[:2])
    except ValueError as error:
        assert "At least three distinct groups" in str(error)
    else:
        raise AssertionError("expected a split validation error")
