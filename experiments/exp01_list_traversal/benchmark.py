"""Benchmark row-wise and column-wise traversal of a Python nested list."""

from __future__ import annotations

import argparse
import csv
import gc
import json
import os
import platform
import random
import statistics
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Measurement:
    size: int
    repeat: int
    order: int
    method: str
    seconds: float
    checksum: int


def make_matrix(size: int) -> list[list[int]]:
    """Create a square matrix while reusing small integer objects."""
    return [[(row + column) % 256 for column in range(size)] for row in range(size)]


def traverse_rows(matrix: Sequence[Sequence[int]]) -> int:
    total = 0
    for row in matrix:
        for value in row:
            total += value
    return total


def traverse_columns(matrix: Sequence[Sequence[int]]) -> int:
    total = 0
    size = len(matrix)
    for column in range(size):
        for row in range(size):
            total += matrix[row][column]
    return total


METHODS: dict[str, Callable[[Sequence[Sequence[int]]], int]] = {
    "row_major": traverse_rows,
    "column_major": traverse_columns,
}


def benchmark_size(size: int, repeats: int, warmups: int, rng: random.Random) -> list[Measurement]:
    matrix = make_matrix(size)
    expected = traverse_rows(matrix)
    if traverse_columns(matrix) != expected:
        raise AssertionError("Traversal checksums differ")

    for _ in range(warmups):
        for function in METHODS.values():
            function(matrix)

    measurements: list[Measurement] = []
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        for repeat in range(1, repeats + 1):
            method_names = list(METHODS)
            rng.shuffle(method_names)
            for order, method in enumerate(method_names, start=1):
                start = time.perf_counter()
                checksum = METHODS[method](matrix)
                elapsed = time.perf_counter() - start
                if checksum != expected:
                    raise AssertionError(f"Incorrect checksum for {method}")
                measurements.append(Measurement(size, repeat, order, method, elapsed, checksum))
    finally:
        if gc_was_enabled:
            gc.enable()
    return measurements


def summarize(measurements: Sequence[Measurement]) -> list[dict[str, float | int | str]]:
    rows: list[dict[str, float | int | str]] = []
    keys = sorted({(item.size, item.method) for item in measurements})
    for size, method in keys:
        values = [item.seconds for item in measurements if item.size == size and item.method == method]
        rows.append(
            {
                "size": size,
                "method": method,
                "runs": len(values),
                "mean_seconds": statistics.fmean(values),
                "median_seconds": statistics.median(values),
                "stdev_seconds": statistics.stdev(values) if len(values) > 1 else 0.0,
                "min_seconds": min(values),
                "max_seconds": max(values),
            }
        )
    return rows


def write_csv(path: Path, rows: Sequence[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def plot_summary(summary: Sequence[dict[str, object]], path: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(path.parent / ".matplotlib-cache"))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(8, 5))
    for method in METHODS:
        rows = [row for row in summary if row["method"] == method]
        axis.plot(
            [int(row["size"]) for row in rows],
            [float(row["median_seconds"]) * 1000 for row in rows],
            marker="o",
            label=method,
        )
    axis.set(title="Nested-list traversal", xlabel="Square matrix size (N)", ylabel="Median time (ms)")
    axis.grid(alpha=0.3)
    axis.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[128, 256, 512, 1024])
    parser.add_argument("--repeats", type=int, default=15)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260711)
    parser.add_argument("--quick", action="store_true", help="Use small sizes and three repeats")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "results")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sizes = [64, 128, 256] if args.quick else args.sizes
    repeats = 3 if args.quick else args.repeats
    if not sizes or any(size <= 0 for size in sizes) or repeats <= 0 or args.warmups < 0:
        raise SystemExit("sizes and repeats must be positive; warmups cannot be negative")

    rng = random.Random(args.seed)
    measurements = [
        item
        for size in sizes
        for item in benchmark_size(size, repeats, args.warmups, rng)
    ]
    summary = summarize(measurements)
    raw_rows = [asdict(item) for item in measurements]
    write_csv(args.output_dir / "raw.csv", raw_rows)
    write_csv(args.output_dir / "summary.csv", summary)
    metadata = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "sizes": sizes,
        "repeats": repeats,
        "warmups": args.warmups,
        "seed": args.seed,
        "timer": "time.perf_counter",
    }
    (args.output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    plot_summary(summary, Path(__file__).parent / "figures" / "median_times.png")

    print(f"{'size':>6}  {'method':>12}  {'median (ms)':>12}  {'mean (ms)':>10}")
    for row in summary:
        print(
            f"{row['size']:>6}  {row['method']:>12}  "
            f"{float(row['median_seconds']) * 1000:>12.3f}  "
            f"{float(row['mean_seconds']) * 1000:>10.3f}"
        )


if __name__ == "__main__":
    main()
