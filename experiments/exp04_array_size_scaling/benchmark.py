"""Measure how array size changes row-first and column-first traversal costs."""

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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numba
import numpy as np
from numba import njit
from numpy.typing import NDArray

Array = NDArray[np.int64]
Traversal = Callable[[Array], int]
Scalar = float | int | str


@dataclass(frozen=True)
class Measurement:
    size: int
    elements: int
    working_set_bytes: int
    repeat: int
    run_order: int
    traversal: str
    seconds: float
    checksum: int


@njit
def row_first(array: Array) -> int:
    total = 0
    rows, columns = array.shape
    for row in range(rows):
        for column in range(columns):
            total += array[row, column]
    return total


@njit
def column_first(array: Array) -> int:
    total = 0
    rows, columns = array.shape
    for column in range(columns):
        for row in range(rows):
            total += array[row, column]
    return total


TRAVERSALS: dict[str, Traversal] = {
    "row_first": row_first,
    "column_first": column_first,
}


def make_array(size: int) -> Array:
    return np.arange(size * size, dtype=np.int64).reshape(size, size)


def benchmark_size(
    size: int, repeats: int, warmups: int, rng: random.Random
) -> list[Measurement]:
    array = make_array(size)
    elements = int(array.size)
    working_set_bytes = int(array.nbytes)
    expected = elements * (elements - 1) // 2
    conditions = list(TRAVERSALS)

    # The first call compiles each dispatcher and is deliberately untimed.
    for traversal, function in TRAVERSALS.items():
        if function(array) != expected:
            raise AssertionError(f"Incorrect checksum for {traversal}")
    for _ in range(warmups):
        for function in TRAVERSALS.values():
            function(array)

    measurements: list[Measurement] = []
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        for repeat in range(1, repeats + 1):
            scheduled = conditions.copy()
            rng.shuffle(scheduled)
            for run_order, traversal in enumerate(scheduled, start=1):
                start = time.perf_counter()
                checksum = TRAVERSALS[traversal](array)
                elapsed = time.perf_counter() - start
                if checksum != expected:
                    raise AssertionError(f"Incorrect checksum for {traversal}")
                measurements.append(
                    Measurement(
                        size,
                        elements,
                        working_set_bytes,
                        repeat,
                        run_order,
                        traversal,
                        elapsed,
                        checksum,
                    )
                )
    finally:
        if gc_was_enabled:
            gc.enable()
    return measurements


def summarize(
    measurements: Sequence[Measurement],
) -> list[dict[str, Scalar]]:
    keys = sorted({(item.size, item.traversal) for item in measurements})
    medians: dict[tuple[int, str], float] = {}
    for key in keys:
        values = [
            item.seconds
            for item in measurements
            if (item.size, item.traversal) == key
        ]
        medians[key] = statistics.median(values)

    rows: list[dict[str, Scalar]] = []
    for size, traversal in keys:
        selected = [
            item
            for item in measurements
            if (item.size, item.traversal) == (size, traversal)
        ]
        values = [item.seconds for item in selected]
        elements = selected[0].elements
        working_set_bytes = selected[0].working_set_bytes
        median = medians[(size, traversal)]
        rows.append(
            {
                "size": size,
                "elements": elements,
                "working_set_bytes": working_set_bytes,
                "traversal": traversal,
                "runs": len(values),
                "mean_seconds": statistics.fmean(values),
                "median_seconds": median,
                "stdev_seconds": statistics.stdev(values) if len(values) > 1 else 0.0,
                "min_seconds": min(values),
                "max_seconds": max(values),
                "throughput_melements_s": elements / median / 1_000_000,
                "slowdown_vs_row": median / medians[(size, "row_first")],
            }
        )
    return rows


def write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def plot_summary(summary: Sequence[Mapping[str, Scalar]], path: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(path.parent / ".matplotlib-cache"))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    figure, (throughput_axis, slowdown_axis) = plt.subplots(1, 2, figsize=(11, 4.5))
    for traversal in TRAVERSALS:
        rows = [row for row in summary if row["traversal"] == traversal]
        throughput_axis.plot(
            [int(row["working_set_bytes"]) / (1024**2) for row in rows],
            [float(row["throughput_melements_s"]) for row in rows],
            marker="o",
            label=traversal,
        )
    throughput_axis.set(
        title="Traversal throughput by working-set size",
        xlabel="Array size (MiB, log scale)",
        ylabel="Throughput (million elements/s)",
        xscale="log",
    )
    throughput_axis.grid(alpha=0.3)
    throughput_axis.legend()

    rows = [row for row in summary if row["traversal"] == "column_first"]
    slowdown_axis.plot(
        [int(row["working_set_bytes"]) / (1024**2) for row in rows],
        [float(row["slowdown_vs_row"]) for row in rows],
        marker="o",
        color="tab:red",
    )
    slowdown_axis.axhline(1.0, color="black", linewidth=1, alpha=0.5)
    slowdown_axis.set(
        title="Column-first traversal penalty",
        xlabel="Array size (MiB, log scale)",
        ylabel="Column-first / row-first median time",
        xscale="log",
    )
    slowdown_axis.grid(alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sizes", nargs="+", type=int, default=[64, 128, 256, 512, 1024, 2048, 4096]
    )
    parser.add_argument("--repeats", type=int, default=11)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260714)
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
    plot_summary(summary, Path(__file__).parent / "figures" / "size_scaling.png")

    print(
        f"{'size':>6}  {'MiB':>8}  {'traversal':>13}  "
        f"{'median (ms)':>12}  {'M elem/s':>10}  {'slowdown':>9}"
    )
    for row in summary:
        print(
            f"{row['size']:>6}  {int(row['working_set_bytes']) / (1024**2):>8.2f}  "
            f"{row['traversal']:>13}  {float(row['median_seconds']) * 1000:>12.3f}  "
            f"{float(row['throughput_melements_s']):>10.1f}  "
            f"{float(row['slowdown_vs_row']):>8.2f}x"
        )


if __name__ == "__main__":
    main()
