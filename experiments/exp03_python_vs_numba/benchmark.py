"""Compare identical array traversals in pure Python and Numba-compiled code."""

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

import numba
import numpy as np
from numba import njit
from numpy.typing import NDArray

Array = NDArray[np.int64]
Traversal = Callable[[Array], int]


@dataclass(frozen=True)
class Measurement:
    size: int
    repeat: int
    run_order: int
    engine: str
    traversal: str
    seconds: float
    checksum: int


def python_row_first(array: Array) -> int:
    total = 0
    rows, columns = array.shape
    for row in range(rows):
        for column in range(columns):
            total += array[row, column]
    return int(total)


def python_column_first(array: Array) -> int:
    total = 0
    rows, columns = array.shape
    for column in range(columns):
        for row in range(rows):
            total += array[row, column]
    return int(total)


numba_row_first = njit(python_row_first)
numba_column_first = njit(python_column_first)

FUNCTIONS: dict[tuple[str, str], Traversal] = {
    ("python", "row_first"): python_row_first,
    ("python", "column_first"): python_column_first,
    ("numba", "row_first"): numba_row_first,
    ("numba", "column_first"): numba_column_first,
}


def make_array(size: int) -> Array:
    return np.arange(size * size, dtype=np.int64).reshape(size, size)


def benchmark_size(
    size: int, repeats: int, warmups: int, rng: random.Random
) -> list[Measurement]:
    array = make_array(size)
    expected = size * size * (size * size - 1) // 2
    conditions = list(FUNCTIONS)

    # The first Numba call compiles each function. It is deliberately untimed.
    for condition in conditions:
        if FUNCTIONS[condition](array) != expected:
            raise AssertionError(f"Incorrect checksum for {condition}")
    for _ in range(warmups):
        for condition in conditions:
            FUNCTIONS[condition](array)

    measurements: list[Measurement] = []
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        for repeat in range(1, repeats + 1):
            scheduled = conditions.copy()
            rng.shuffle(scheduled)
            for run_order, (engine, traversal) in enumerate(scheduled, start=1):
                start = time.perf_counter()
                checksum = FUNCTIONS[(engine, traversal)](array)
                elapsed = time.perf_counter() - start
                if checksum != expected:
                    raise AssertionError(f"Incorrect checksum for {engine}/{traversal}")
                measurements.append(
                    Measurement(
                        size, repeat, run_order, engine, traversal, elapsed, checksum
                    )
                )
    finally:
        if gc_was_enabled:
            gc.enable()
    return measurements


def summarize(
    measurements: Sequence[Measurement],
) -> list[dict[str, float | int | str]]:
    keys = sorted({(item.size, item.engine, item.traversal) for item in measurements})
    medians: dict[tuple[int, str, str], float] = {}
    for key in keys:
        values = [
            item.seconds
            for item in measurements
            if (item.size, item.engine, item.traversal) == key
        ]
        medians[key] = statistics.median(values)

    rows: list[dict[str, float | int | str]] = []
    for size, engine, traversal in keys:
        values = [
            item.seconds
            for item in measurements
            if (item.size, item.engine, item.traversal) == (size, engine, traversal)
        ]
        rows.append(
            {
                "size": size,
                "engine": engine,
                "traversal": traversal,
                "runs": len(values),
                "mean_seconds": statistics.fmean(values),
                "median_seconds": medians[(size, engine, traversal)],
                "stdev_seconds": statistics.stdev(values) if len(values) > 1 else 0.0,
                "min_seconds": min(values),
                "max_seconds": max(values),
                "speedup_vs_python": (
                    medians[(size, "python", traversal)]
                    / medians[(size, engine, traversal)]
                ),
                "column_vs_row_slowdown": (
                    medians[(size, engine, "column_first")]
                    / medians[(size, engine, "row_first")]
                ),
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
    figure, (time_axis, ratio_axis) = plt.subplots(1, 2, figsize=(11, 4.5))
    for engine in ("python", "numba"):
        for traversal in ("row_first", "column_first"):
            rows = [
                row
                for row in summary
                if row["engine"] == engine and row["traversal"] == traversal
            ]
            time_axis.plot(
                [int(row["size"]) for row in rows],
                [float(row["median_seconds"]) * 1000 for row in rows],
                marker="o",
                label=f"{engine} / {traversal}",
            )
    time_axis.set(
        title="Execution time (log scale)",
        xlabel="Square array size (N)",
        ylabel="Median time (ms)",
        yscale="log",
    )
    time_axis.grid(alpha=0.3)
    time_axis.legend(fontsize=8)

    for engine in ("python", "numba"):
        rows = [
            row
            for row in summary
            if row["engine"] == engine and row["traversal"] == "row_first"
        ]
        ratio_axis.plot(
            [int(row["size"]) for row in rows],
            [float(row["column_vs_row_slowdown"]) for row in rows],
            marker="o",
            label=engine,
        )
    ratio_axis.axhline(1.0, color="black", linewidth=1, alpha=0.5)
    ratio_axis.set(
        title="Traversal-order penalty",
        xlabel="Square array size (N)",
        ylabel="Column-first / row-first",
    )
    ratio_axis.grid(alpha=0.3)
    ratio_axis.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[256, 512, 1024])
    parser.add_argument("--repeats", type=int, default=11)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260713)
    parser.add_argument(
        "--quick", action="store_true", help="Use small sizes and three repeats"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path(__file__).parent / "results"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sizes = [32, 64, 128] if args.quick else args.sizes
    repeats = 3 if args.quick else args.repeats
    if (
        not sizes
        or any(size <= 0 for size in sizes)
        or repeats <= 0
        or args.warmups < 0
    ):
        raise SystemExit(
            "sizes and repeats must be positive; warmups cannot be negative"
        )

    rng = random.Random(args.seed)
    measurements = [
        item
        for size in sizes
        for item in benchmark_size(size, repeats, args.warmups, rng)
    ]
    summary = summarize(measurements)
    write_csv(args.output_dir / "raw.csv", [asdict(item) for item in measurements])
    write_csv(args.output_dir / "summary.csv", summary)
    metadata = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "numpy": np.__version__,
        "numba": numba.__version__,
        "platform": platform.platform(),
        "sizes": sizes,
        "dtype": "int64",
        "memory_layout": "C-order",
        "repeats": repeats,
        "warmups_after_compilation": args.warmups,
        "seed": args.seed,
        "timer": "time.perf_counter",
        "numba_compilation_included": False,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    plot_summary(summary, Path(__file__).parent / "figures" / "median_times.png")

    print(
        f"{'size':>6}  {'engine':>7}  {'traversal':>13}  "
        f"{'median (ms)':>12}  {'speedup':>9}  {'col/row':>8}"
    )
    for row in summary:
        print(
            f"{row['size']:>6}  {row['engine']:>7}  {row['traversal']:>13}  "
            f"{float(row['median_seconds']) * 1000:>12.3f}  "
            f"{float(row['speedup_vs_python']):>8.2f}x  "
            f"{float(row['column_vs_row_slowdown']):>7.2f}x"
        )


if __name__ == "__main__":
    main()
