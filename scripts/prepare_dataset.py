"""Validate raw telemetry and write causal processed features."""
import argparse
from pathlib import Path
from pumpguard.data.pipeline import read_csv, write_csv
from pumpguard.data.features import engineer_features

def main() -> None:
    """Validate, engineer features, and save processed CSV separately from raw."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/raw/pump_telemetry.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/pump_features.csv"))
    parser.add_argument("--windows", default="3,5", help="Comma-separated rolling window sizes")
    parser.add_argument("--lags", default="1", help="Comma-separated lag steps")
    args = parser.parse_args()
    try:
        windows = tuple(int(value) for value in args.windows.split(",") if value.strip())
        lags = tuple(int(value) for value in args.lags.split(",") if value.strip())
        raw = read_csv(args.input)
        processed = engineer_features(raw, windows=windows, lags=lags)
        write_csv(processed, args.output)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(f"Validated {len(raw)} rows; wrote causal features to {args.output}")

if __name__ == "__main__":
    main()
