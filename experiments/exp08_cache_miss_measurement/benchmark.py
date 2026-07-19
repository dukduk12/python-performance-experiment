"""Collect cache counters for row-first and column-first traversal with Linux perf."""

from __future__ import annotations

import argparse
import csv
import json
import platform
import random
import shutil
import statistics
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

CONDITIONS = ("row_first", "column_first")
EVENTS = ("cache-references", "cache-misses")


@dataclass(frozen=True)
class Measurement:
    condition: str
    repeat: int
    run_order: int
    median_seconds: float
    total_timed_seconds: float
    cache_references: int
    cache_misses: int
    miss_rate_percent: float


def parse_perf_csv(text: str) -> dict[str, int]:
    """Parse the semicolon-delimited output emitted by ``perf stat -x ';'``."""
    counters: dict[str, int] = {}
    for line in text.splitlines():
        fields = [field.strip() for field in line.split(";")]
        if len(fields) < 3:
            continue
        value, _, event = fields[:3]
        event = event.split(":", maxsplit=1)[0]
        if event not in EVENTS or value.startswith("<"):
            continue
        try:
            counters[event] = int(value.replace(",", ""))
        except ValueError:
            continue
    missing = set(EVENTS) - counters.keys()
    if missing:
        raise RuntimeError(
            "perf did not report usable counters for: " + ", ".join(sorted(missing))
        )
    return counters


def collect_once(
    condition: str,
    size: int,
    iterations: int,
    warmups: int,
    repeat: int,
    run_order: int,
    python: str = sys.executable,
) -> Measurement:
    kernel = Path(__file__).with_name("kernel.py")
    command = [
        "perf",
        "stat",
        "-x",
        ";",
        "-e",
        ",".join(EVENTS),
        "--",
        python,
        str(kernel),
        condition,
        "--size",
        str(size),
        "--iterations",
        str(iterations),
        "--warmups",
        str(warmups),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode:
        raise RuntimeError(
            "perf stat failed. Check Linux perf installation and perf_event permissions.\n"
            + completed.stderr.strip()
        )
    workload = json.loads(completed.stdout.strip().splitlines()[-1])
    counters = parse_perf_csv(completed.stderr)
    references = counters["cache-references"]
    misses = counters["cache-misses"]
    return Measurement(
        condition=condition,
        repeat=repeat,
        run_order=run_order,
        median_seconds=float(workload["median_seconds"]),
        total_timed_seconds=float(workload["total_timed_seconds"]),
        cache_references=references,
        cache_misses=misses,
        miss_rate_percent=100.0 * misses / references if references else 0.0,
    )


def summarize(measurements: Sequence[Measurement]) -> list[dict[str, float | int | str]]:
    row_time = statistics.median(
        item.median_seconds for item in measurements if item.condition == "row_first"
    )
    rows: list[dict[str, float | int | str]] = []
    for condition in CONDITIONS:
        selected = [item for item in measurements if item.condition == condition]
        if not selected:
            continue
        times = [item.median_seconds for item in selected]
        references = [item.cache_references for item in selected]
        misses = [item.cache_misses for item in selected]
        rates = [item.miss_rate_percent for item in selected]
        median_time = statistics.median(times)
        rows.append(
            {
                "condition": condition,
                "runs": len(selected),
                "median_seconds": median_time,
                "stdev_seconds": statistics.stdev(times) if len(times) > 1 else 0.0,
                "median_cache_references": statistics.median(references),
                "median_cache_misses": statistics.median(misses),
                "median_miss_rate_percent": statistics.median(rates),
                "slowdown_vs_row": median_time / row_time,
            }
        )
    return rows


def write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=4096)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--seed", type=int, default=20260719)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument(
        "--output-dir", type=Path, default=Path(__file__).parent / "results"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if platform.system() != "Linux" or shutil.which("perf") is None:
        raise SystemExit("Experiment 08 requires Linux and the `perf` executable")
    size = 512 if args.quick else args.size
    repeats = 2 if args.quick else args.repeats
    iterations = 2 if args.quick else args.iterations
    if size <= 0 or iterations <= 0 or repeats <= 0 or args.warmups < 0:
        raise SystemExit("size, iterations and repeats must be positive")

    rng = random.Random(args.seed)
    measurements: list[Measurement] = []
    for repeat in range(1, repeats + 1):
        scheduled = list(CONDITIONS)
        rng.shuffle(scheduled)
        for run_order, condition in enumerate(scheduled, start=1):
            measurements.append(
                collect_once(
                    condition,
                    size,
                    iterations,
                    args.warmups,
                    repeat,
                    run_order,
                )
            )
    summary = summarize(measurements)
    write_csv(args.output_dir / "raw.csv", [asdict(item) for item in measurements])
    write_csv(args.output_dir / "summary.csv", summary)
    metadata = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "size": size,
        "dtype": "float64",
        "array_order": "C",
        "iterations_per_perf_invocation": iterations,
        "warmups": args.warmups,
        "repeats": repeats,
        "seed": args.seed,
        "perf_events": list(EVENTS),
        "counter_scope": "whole kernel process, including common startup and setup",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    for row in summary:
        print(
            f"{row['condition']:>12}: {float(row['median_seconds']) * 1000:.3f} ms, "
            f"{float(row['median_miss_rate_percent']):.2f}% misses, "
            f"{float(row['slowdown_vs_row']):.2f}x row time"
        )


if __name__ == "__main__":
    main()
