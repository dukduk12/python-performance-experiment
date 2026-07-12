"""Benchmark traversal direction against NumPy C-order and F-order layouts."""

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

import numpy as np
from numpy.typing import NDArray

Array = NDArray[np.int64]


@dataclass(frozen=True)
class Measurement:
    size: int
    repeat: int
    run_order: int
    layout: str
    traversal: str
    seconds: float
    checksum: int
    stride_0: int
    stride_1: int


def make_arrays(size: int) -> dict[str, Array]:
    values = np.arange(size * size, dtype=np.int64).reshape(size, size)
    return {"C": np.array(values, order="C"), "F": np.array(values, order="F")}


def traverse_rows(array: Array) -> int:
    total = 0
    rows, columns = array.shape
    for row in range(rows):
        for column in range(columns):
            total += int(array[row, column])
    return total


def traverse_columns(array: Array) -> int:
    total = 0
    rows, columns = array.shape
    for column in range(columns):
        for row in range(rows):
            total += int(array[row, column])
    return total


TRAVERSALS: dict[str, Callable[[Array], int]] = {
    "row_first": traverse_rows,
    "column_first": traverse_columns,
}


def benchmark_size(size: int, repeats: int, warmups: int, rng: random.Random) -> list[Measurement]:
    arrays = make_arrays(size)
    expected = size * size * (size * size - 1) // 2
    conditions = [(layout, traversal) for layout in arrays for traversal in TRAVERSALS]

    for array in arrays.values():
        for function in TRAVERSALS.values():
            if function(array) != expected:
                raise AssertionError("Traversal checksum differs from the expected value")
    for _ in range(warmups):
        for layout, traversal in conditions:
            TRAVERSALS[traversal](arrays[layout])

    measurements: list[Measurement] = []
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        for repeat in range(1, repeats + 1):
            scheduled = conditions.copy()
            rng.shuffle(scheduled)
            for run_order, (layout, traversal) in enumerate(scheduled, start=1):
                array = arrays[layout]
                start = time.perf_counter()
                checksum = TRAVERSALS[traversal](array)
                elapsed = time.perf_counter() - start
                if checksum != expected:
                    raise AssertionError(f"Incorrect checksum for {layout}/{traversal}")
                measurements.append(
                    Measurement(
                        size, repeat, run_order, layout, traversal, elapsed, checksum,
                        int(array.strides[0]), int(array.strides[1]),
                    )
                )
    finally:
        if gc_was_enabled:
            gc.enable()
    return measurements


def summarize(measurements: Sequence[Measurement]) -> list[dict[str, float | int | str]]:
    rows: list[dict[str, float | int | str]] = []
    keys = sorted({(item.size, item.layout, item.traversal) for item in measurements})
    medians: dict[tuple[int, str, str], float] = {}
    for key in keys:
        values = [item.seconds for item in measurements if (item.size, item.layout, item.traversal) == key]
        medians[key] = statistics.median(values)
    for size, layout, traversal in keys:
        values = [item.seconds for item in measurements if (item.size, item.layout, item.traversal) == (size, layout, traversal)]
        matched = "row_first" if layout == "C" else "column_first"
        rows.append({
            "size": size,
            "layout": layout,
            "traversal": traversal,
            "stride_0": next(item.stride_0 for item in measurements if item.size == size and item.layout == layout),
            "stride_1": next(item.stride_1 for item in measurements if item.size == size and item.layout == layout),
            "runs": len(values),
            "mean_seconds": statistics.fmean(values),
            "median_seconds": medians[(size, layout, traversal)],
            "stdev_seconds": statistics.stdev(values) if len(values) > 1 else 0.0,
            "min_seconds": min(values),
            "max_seconds": max(values),
            "slowdown_vs_matched": medians[(size, layout, traversal)] / medians[(size, layout, matched)],
        })
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
    for layout in ("C", "F"):
        for traversal in TRAVERSALS:
            rows = [row for row in summary if row["layout"] == layout and row["traversal"] == traversal]
            axis.plot([int(row["size"]) for row in rows],
                      [float(row["median_seconds"]) * 1000 for row in rows],
                      marker="o", label=f"{layout}-order / {traversal}")
    axis.set(title="NumPy memory layout and traversal", xlabel="Square array size (N)", ylabel="Median time (ms)")
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
    parser.add_argument("--seed", type=int, default=20260712)
    parser.add_argument("--quick", action="store_true", help="Use small sizes and three repeats")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "results")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sizes = [32, 64, 128] if args.quick else args.sizes
    repeats = 3 if args.quick else args.repeats
    if not sizes or any(size <= 0 for size in sizes) or repeats <= 0 or args.warmups < 0:
        raise SystemExit("sizes and repeats must be positive; warmups cannot be negative")

    rng = random.Random(args.seed)
    measurements = [item for size in sizes for item in benchmark_size(size, repeats, args.warmups, rng)]
    summary = summarize(measurements)
    write_csv(args.output_dir / "raw.csv", [asdict(item) for item in measurements])
    write_csv(args.output_dir / "summary.csv", summary)
    metadata = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(), "python": sys.version,
        "numpy": np.__version__, "platform": platform.platform(), "sizes": sizes,
        "dtype": "int64", "repeats": repeats, "warmups": args.warmups,
        "seed": args.seed, "timer": "time.perf_counter",
    }
    (args.output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    plot_summary(summary, Path(__file__).parent / "figures" / "median_times.png")
    print(f"{'size':>6}  {'layout':>6}  {'traversal':>13}  {'median (ms)':>12}  {'slowdown':>9}")
    for row in summary:
        print(f"{row['size']:>6}  {row['layout']:>6}  {row['traversal']:>13}  "
              f"{float(row['median_seconds']) * 1000:>12.3f}  {float(row['slowdown_vs_matched']):>8.2f}x")


if __name__ == "__main__":
    main()
