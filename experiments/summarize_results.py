from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert experiment JSON files to a tidy CSV table.")
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    rows: list[dict[str, object]] = []
    for path in args.inputs:
        result = json.loads(path.read_text(encoding="utf-8"))
        for metric, value in result.get("metrics", {}).items():
            rows.append(
                {
                    "experiment": result["experiment"],
                    "timestamp_utc": result["timestamp_utc"],
                    "git_commit": result["git_commit"],
                    "passed": result["passed"],
                    "metric": metric,
                    "value": value,
                }
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["experiment", "timestamp_utc", "git_commit", "passed", "metric", "value"],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
