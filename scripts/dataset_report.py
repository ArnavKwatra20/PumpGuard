"""Write JSON and Markdown quality reports for a synthetic CSV."""
import argparse
import csv
from pathlib import Path
from pumpguard.data.pipeline import validate_rows
from pumpguard.data.splitting import split_dataset
from pumpguard.data.quality import build_quality_report, write_quality_report

def main() -> None:
    """Audit input data and write machine-readable and human-readable reports."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/raw/pump_telemetry.csv"))
    parser.add_argument("--json-output", type=Path, default=Path("data/reports/quality_report.json"))
    parser.add_argument("--markdown-output", type=Path, default=Path("data/reports/quality_report.md"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if not args.input.is_file():
        parser.error(f"Input CSV not found: {args.input}")
    with args.input.open("r", newline="", encoding="utf-8-sig") as stream:
        raw = list(csv.DictReader(stream))
    error = None
    metadata = None
    try:
        valid = validate_rows(raw)
        _, metadata = split_dataset(valid, seed=args.seed)
    except ValueError as exc:
        error = str(exc)
    report = build_quality_report(raw, split_metadata=metadata, validation_error=error)
    write_quality_report(report, args.json_output, args.markdown_output)
    print(f"Wrote synthetic quality reports: {args.json_output} and {args.markdown_output}")
    if error:
        print(f"Data-quality validation warning: {error}")

if __name__ == "__main__":
    main()
