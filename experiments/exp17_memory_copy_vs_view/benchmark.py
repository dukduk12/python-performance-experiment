"""Measure the creation-time and memory cost of NumPy copies and views."""

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
import tracemalloc
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

CONDITIONS = ("copy", "slice_view", "ndarray_view")
Scalar = bool | float | int | str


@dataclass(frozen=True)
class Measurement:
    condition: str
    size: int
    elements: int
    source_nbytes: int
    result_nbytes: int
    owns_data: bool
    shares_memory: bool
    repeat: int
    run_order: int
    seconds: float
    traced_peak_bytes: int


def create_source(size: int) -> NDArray[np.float64]:
    """Create the shared source outside the measured region."""
    return np.arange(size * size, dtype=np.float64).reshape(size, size)


def create_result(source: NDArray[np.float64], condition: str) -> NDArray[np.float64]:
    """Apply one of the three creation operations."""
    operations: dict[str, Callable[[], NDArray[np.float64]]] = {
        "copy": source.copy,
        "slice_view": lambda: source[:, :],
        "ndarray_view": source.view,
    }
    try:
        return operations[condition]()
    except KeyError as error:
        raise ValueError(f"unknown condition: {condition}") from error


def measure_once(
    source: NDArray[np.float64],
    condition: str,
    repeat: int,
    run_order: int,
) -> tuple[Measurement, NDArray[np.float64]]:
    """Measure creation while retaining the result until allocation is sampled."""
    tracemalloc.start()
    start = time.perf_counter_ns()
    result = create_result(source, condition)
    elapsed = (time.perf_counter_ns() - start) / 1_000_000_000
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    measurement = Measurement(
        condition=condition,
        size=source.shape[0],
        elements=int(source.size),
        source_nbytes=int(source.nbytes),
        result_nbytes=int(result.nbytes),
        owns_data=bool(result.flags.owndata),
        shares_memory=bool(np.shares_memory(source, result)),
        repeat=repeat,
        run_order=run_order,
        seconds=elapsed,
        traced_peak_bytes=peak,
    )
    return measurement, result


def benchmark_operations(
    sizes: Sequence[int],
    repeats: int,
    warmups: int,
    rng: random.Random,
) -> list[Measurement]:
    measurements: list[Measurement] = []
    for size in sizes:
        source = create_source(size)
        for condition in CONDITIONS:
            for _ in range(warmups):
                result = create_result(source, condition)
                if not np.array_equal(source, result):
                    raise AssertionError("operation changed array values")
                del result
        gc.collect()
        for repeat in range(1, repeats + 1):
            scheduled = list(CONDITIONS)
            rng.shuffle(scheduled)
            for run_order, condition in enumerate(scheduled, start=1):
                measurement, result = measure_once(source, condition, repeat, run_order)
                if not np.array_equal(source, result):
                    raise AssertionError("operation changed array values")
                measurements.append(measurement)
                del result
    return measurements


def summarize(measurements: Sequence[Measurement]) -> list[dict[str, Scalar]]:
    rows: list[dict[str, Scalar]] = []
    sizes = sorted({item.size for item in measurements})
    for size in sizes:
        selected_size = [item for item in measurements if item.size == size]
        copy_median = statistics.median(
            item.seconds for item in selected_size if item.condition == "copy"
        )
        for condition in CONDITIONS:
            selected = [item for item in selected_size if item.condition == condition]
            if not selected:
                continue
            times = [item.seconds for item in selected]
            peaks = [item.traced_peak_bytes for item in selected]
            median = statistics.median(times)
            sample = selected[0]
            rows.append(
                {
                    "condition": condition,
                    "size": size,
                    "shape": f"{size}x{size}",
                    "source_mib": sample.source_nbytes / 1024**2,
                    "owns_data": sample.owns_data,
                    "shares_memory": sample.shares_memory,
                    "runs": len(selected),
                    "mean_seconds": statistics.fmean(times),
                    "median_seconds": median,
                    "stdev_seconds": statistics.stdev(times) if len(times) > 1 else 0.0,
                    "median_traced_peak_bytes": statistics.median(peaks),
                    "speedup_vs_copy": copy_median / median,
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

    sizes = sorted({int(row["size"]) for row in summary})
    path.parent.mkdir(parents=True, exist_ok=True)
    figure, (time_axis, memory_axis) = plt.subplots(1, 2, figsize=(11, 4.5))
    for condition in CONDITIONS:
        rows = [row for row in summary if row["condition"] == condition]
        time_axis.plot(
            sizes,
            [float(row["median_seconds"]) * 1e6 for row in rows],
            marker="o",
            label=condition,
        )
        memory_axis.plot(
            sizes,
            [float(row["median_traced_peak_bytes"]) / 1024**2 for row in rows],
            marker="o",
            label=condition,
        )
    time_axis.set(
        title="Array creation time",
        xlabel="Square-array side length",
        ylabel="Median time (µs, log scale)",
        yscale="log",
    )
    memory_axis.set(
        title="Allocation during creation",
        xlabel="Square-array side length",
        ylabel="Median traced peak (MiB, log scale)",
        yscale="log",
    )
    for axis in (time_axis, memory_axis):
        axis.grid(alpha=0.3)
        axis.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=[256, 1024, 2048])
    parser.add_argument("--repeats", type=int, default=11)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260727)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "results")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sizes = [64, 256] if args.quick else args.sizes
    repeats = 3 if args.quick else args.repeats
    if not sizes or any(size <= 0 for size in sizes) or repeats <= 0 or args.warmups < 0:
        raise SystemExit("sizes and repeats must be positive; warmups cannot be negative")
    measurements = benchmark_operations(
        sizes, repeats, args.warmups, random.Random(args.seed)
    )
    summary = summarize(measurements)
    write_csv(args.output_dir / "raw.csv", [asdict(item) for item in measurements])
    write_csv(args.output_dir / "summary.csv", summary)
    metadata = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "numpy": np.__version__,
        "platform": platform.platform(),
        "sizes": sizes,
        "dtype": "float64",
        "repeats": repeats,
        "warmups": args.warmups,
        "seed": args.seed,
        "timer": "time.perf_counter_ns",
        "memory_profiler": "tracemalloc peak during result creation",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    plot_summary(summary, Path(__file__).parent / "figures" / "copy_vs_view.png")
    print(f"{'shape':>11}  {'condition':>13}  {'median (us)':>12}  {'peak (MiB)':>11}  {'speedup':>9}")
    for row in summary:
        print(
            f"{row['shape']:>11}  {row['condition']:>13}  "
            f"{float(row['median_seconds']) * 1e6:>12.2f}  "
            f"{float(row['median_traced_peak_bytes']) / 1024**2:>11.4f}  "
            f"{float(row['speedup_vs_copy']):>8.1f}x"
        )


if __name__ == "__main__":
    main()
