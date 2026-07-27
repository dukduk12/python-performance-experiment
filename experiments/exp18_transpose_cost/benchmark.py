"""Separate NumPy transpose creation cost from traversal cost."""

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
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

CONDITIONS = ("transpose_view", "contiguous_copy")
Scalar = bool | float | int | str


@dataclass(frozen=True)
class Measurement:
    condition: str
    size: int
    elements: int
    source_nbytes: int
    repeat: int
    run_order: int
    creation_seconds: float
    traversal_seconds: float
    traced_peak_bytes: int
    c_contiguous: bool
    f_contiguous: bool
    owns_data: bool
    shares_memory: bool
    checksum: float


def create_source(size: int) -> NDArray[np.float64]:
    """Build a deterministic C-contiguous source outside measured regions."""
    return np.arange(size * size, dtype=np.float64).reshape(size, size)


def create_transpose(
    source: NDArray[np.float64], condition: str
) -> NDArray[np.float64]:
    """Return either the metadata-only transpose or its C-contiguous copy."""
    if condition == "transpose_view":
        return source.T
    if condition == "contiguous_copy":
        return np.ascontiguousarray(source.T)
    raise ValueError(f"unknown condition: {condition}")


def traverse(array: NDArray[np.float64]) -> float:
    """Reduce logical rows, forcing each row to be visited along axis 1."""
    return float(np.sum(array, axis=1).sum())


def measure_once(
    source: NDArray[np.float64],
    condition: str,
    repeat: int,
    run_order: int,
) -> Measurement:
    """Measure result creation and a later full-array traversal separately."""
    tracemalloc.start()
    start = time.perf_counter_ns()
    result = create_transpose(source, condition)
    creation_seconds = (time.perf_counter_ns() - start) / 1_000_000_000
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    start = time.perf_counter_ns()
    checksum = traverse(result)
    traversal_seconds = (time.perf_counter_ns() - start) / 1_000_000_000
    return Measurement(
        condition=condition,
        size=source.shape[0],
        elements=int(source.size),
        source_nbytes=int(source.nbytes),
        repeat=repeat,
        run_order=run_order,
        creation_seconds=creation_seconds,
        traversal_seconds=traversal_seconds,
        traced_peak_bytes=peak,
        c_contiguous=bool(result.flags.c_contiguous),
        f_contiguous=bool(result.flags.f_contiguous),
        owns_data=bool(result.flags.owndata),
        shares_memory=bool(np.shares_memory(source, result)),
        checksum=checksum,
    )


def benchmark_operations(
    sizes: Sequence[int],
    repeats: int,
    warmups: int,
    rng: random.Random,
) -> list[Measurement]:
    measurements: list[Measurement] = []
    for size in sizes:
        source = create_source(size)
        expected = float(np.sum(source))
        for condition in CONDITIONS:
            for _ in range(warmups):
                if traverse(create_transpose(source, condition)) != expected:
                    raise AssertionError("transpose changed array values")
        gc.collect()
        for repeat in range(1, repeats + 1):
            scheduled = list(CONDITIONS)
            rng.shuffle(scheduled)
            for run_order, condition in enumerate(scheduled, start=1):
                item = measure_once(source, condition, repeat, run_order)
                if item.checksum != expected:
                    raise AssertionError("transpose traversal produced a wrong checksum")
                measurements.append(item)
    return measurements


def summarize(measurements: Sequence[Measurement]) -> list[dict[str, Scalar]]:
    rows: list[dict[str, Scalar]] = []
    for size in sorted({item.size for item in measurements}):
        selected_size = [item for item in measurements if item.size == size]
        view_traversal = statistics.median(
            item.traversal_seconds
            for item in selected_size
            if item.condition == "transpose_view"
        )
        for condition in CONDITIONS:
            selected = [item for item in selected_size if item.condition == condition]
            creation = [item.creation_seconds for item in selected]
            traversal = [item.traversal_seconds for item in selected]
            sample = selected[0]
            median_traversal = statistics.median(traversal)
            rows.append(
                {
                    "condition": condition,
                    "size": size,
                    "shape": f"{size}x{size}",
                    "source_mib": sample.source_nbytes / 1024**2,
                    "runs": len(selected),
                    "median_creation_seconds": statistics.median(creation),
                    "median_traversal_seconds": median_traversal,
                    "stdev_traversal_seconds": (
                        statistics.stdev(traversal) if len(traversal) > 1 else 0.0
                    ),
                    "median_traced_peak_bytes": statistics.median(
                        item.traced_peak_bytes for item in selected
                    ),
                    "c_contiguous": sample.c_contiguous,
                    "f_contiguous": sample.f_contiguous,
                    "owns_data": sample.owns_data,
                    "shares_memory": sample.shares_memory,
                    "traversal_speedup_vs_view": view_traversal / median_traversal,
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
    figure, axes = plt.subplots(1, 3, figsize=(14, 4.5))
    fields = (
        ("median_creation_seconds", "Creation time", "Median time (µs)"),
        ("median_traversal_seconds", "Later traversal time", "Median time (ms)"),
        ("median_traced_peak_bytes", "Creation allocation", "Median peak (MiB)"),
    )
    scales = (1e6, 1e3, 1 / 1024**2)
    for condition in CONDITIONS:
        rows = [row for row in summary if row["condition"] == condition]
        for axis, (field, title, ylabel), scale in zip(axes, fields, scales):
            axis.plot(
                sizes,
                [float(row[field]) * scale for row in rows],
                marker="o",
                label=condition,
            )
            axis.set(title=title, xlabel="Square-array side length", ylabel=ylabel)
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
    parser.add_argument("--seed", type=int, default=20260728)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument(
        "--output-dir", type=Path, default=Path(__file__).parent / "results"
    )
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
        "traversal": "np.sum(array, axis=1).sum() (logical row traversal)",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    plot_summary(summary, Path(__file__).parent / "figures" / "transpose_cost.png")
    print(
        f"{'shape':>11}  {'condition':>16}  {'create (us)':>12}  "
        f"{'traverse (ms)':>13}  {'peak (MiB)':>11}"
    )
    for row in summary:
        print(
            f"{row['shape']:>11}  {row['condition']:>16}  "
            f"{float(row['median_creation_seconds']) * 1e6:>12.2f}  "
            f"{float(row['median_traversal_seconds']) * 1e3:>13.4f}  "
            f"{float(row['median_traced_peak_bytes']) / 1024**2:>11.4f}"
        )


if __name__ == "__main__":
    main()
