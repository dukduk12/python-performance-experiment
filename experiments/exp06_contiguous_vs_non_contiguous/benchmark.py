"""Compare NumPy copy performance across contiguous and strided array views."""

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
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

CONDITIONS = ("contiguous", "sliced_view", "transposed_view")
Scalar = bool | float | int | str


@dataclass(frozen=True)
class Measurement:
    condition: str
    rows: int
    columns: int
    elements: int
    itemsize_bytes: int
    stride_0_bytes: int
    stride_1_bytes: int
    c_contiguous: bool
    f_contiguous: bool
    repeat: int
    run_order: int
    seconds: float


def make_arrays(rows: int, columns: int) -> dict[str, NDArray]:
    """Build equal-shaped arrays whose layouts differ without timing allocation."""
    contiguous = np.arange(rows * columns, dtype=np.float64).reshape(rows, columns)
    padded = np.empty((rows, columns * 2), dtype=np.float64)
    padded[:, ::2] = contiguous
    padded[:, 1::2] = -1.0
    transpose_base = np.arange(rows * columns, dtype=np.float64).reshape(columns, rows)
    arrays = {
        "contiguous": contiguous,
        "sliced_view": padded[:, ::2],
        "transposed_view": transpose_base.T,
    }
    if any(array.shape != (rows, columns) for array in arrays.values()):
        raise AssertionError("Every condition must have the same logical shape")
    return arrays


def benchmark_layouts(
    rows: int,
    columns: int,
    repeats: int,
    warmups: int,
    rng: random.Random,
) -> list[Measurement]:
    arrays = make_arrays(rows, columns)
    destination = np.empty((rows, columns), dtype=np.float64)
    for source in arrays.values():
        np.copyto(destination, source)
        if not np.array_equal(destination, source):
            raise AssertionError("Validation copy did not preserve values")
        for _ in range(warmups):
            np.copyto(destination, source)

    measurements: list[Measurement] = []
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        for repeat in range(1, repeats + 1):
            scheduled = list(CONDITIONS)
            rng.shuffle(scheduled)
            for run_order, condition in enumerate(scheduled, start=1):
                source = arrays[condition]
                start = time.perf_counter()
                np.copyto(destination, source)
                elapsed = time.perf_counter() - start
                measurements.append(
                    Measurement(
                        condition=condition,
                        rows=rows,
                        columns=columns,
                        elements=int(source.size),
                        itemsize_bytes=int(source.itemsize),
                        stride_0_bytes=int(source.strides[0]),
                        stride_1_bytes=int(source.strides[1]),
                        c_contiguous=bool(source.flags.c_contiguous),
                        f_contiguous=bool(source.flags.f_contiguous),
                        repeat=repeat,
                        run_order=run_order,
                        seconds=elapsed,
                    )
                )
    finally:
        if gc_was_enabled:
            gc.enable()
    return measurements


def summarize(measurements: Sequence[Measurement]) -> list[dict[str, Scalar]]:
    rows: list[dict[str, Scalar]] = []
    baseline = statistics.median(
        item.seconds for item in measurements if item.condition == "contiguous"
    )
    for condition in CONDITIONS:
        selected = [item for item in measurements if item.condition == condition]
        if not selected:
            continue
        values = [item.seconds for item in selected]
        median = statistics.median(values)
        sample = selected[0]
        rows.append(
            {
                "condition": condition,
                "shape": f"{sample.rows}x{sample.columns}",
                "strides_bytes": f"({sample.stride_0_bytes}, {sample.stride_1_bytes})",
                "c_contiguous": sample.c_contiguous,
                "f_contiguous": sample.f_contiguous,
                "runs": len(values),
                "mean_seconds": statistics.fmean(values),
                "median_seconds": median,
                "stdev_seconds": statistics.stdev(values) if len(values) > 1 else 0.0,
                "min_seconds": min(values),
                "max_seconds": max(values),
                "throughput_melements_s": sample.elements / median / 1_000_000,
                "slowdown_vs_contiguous": median / baseline,
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

    labels = [str(row["condition"]).replace("_", "\n") for row in summary]
    path.parent.mkdir(parents=True, exist_ok=True)
    figure, (time_axis, slowdown_axis) = plt.subplots(1, 2, figsize=(11, 4.5))
    time_axis.bar(labels, [float(row["median_seconds"]) * 1000 for row in summary])
    time_axis.set(title="Copy time by layout", ylabel="Median time (ms)")
    time_axis.grid(axis="y", alpha=0.3)
    slowdown_axis.bar(
        labels, [float(row["slowdown_vs_contiguous"]) for row in summary], color="tab:orange"
    )
    slowdown_axis.axhline(1.0, color="black", linewidth=1)
    slowdown_axis.set(title="Relative cost", ylabel="Slowdown vs contiguous")
    slowdown_axis.grid(axis="y", alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=2_000)
    parser.add_argument("--columns", type=int, default=4_000)
    parser.add_argument("--repeats", type=int, default=11)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260716)
    parser.add_argument("--quick", action="store_true", help="Use a 200x400 array and three repeats")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "results")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows, columns = (200, 400) if args.quick else (args.rows, args.columns)
    repeats = 3 if args.quick else args.repeats
    if rows <= 0 or columns <= 0 or repeats <= 0 or args.warmups < 0:
        raise SystemExit("dimensions and repeats must be positive; warmups cannot be negative")
    measurements = benchmark_layouts(
        rows, columns, repeats, args.warmups, random.Random(args.seed)
    )
    summary = summarize(measurements)
    write_csv(args.output_dir / "raw.csv", [asdict(item) for item in measurements])
    write_csv(args.output_dir / "summary.csv", summary)
    metadata = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "numpy": np.__version__,
        "platform": platform.platform(),
        "shape": [rows, columns],
        "dtype": "float64",
        "operation": "numpy.copyto into a C-contiguous destination",
        "repeats": repeats,
        "warmups": args.warmups,
        "seed": args.seed,
        "timer": "time.perf_counter",
        "allocation_included": False,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    plot_summary(summary, Path(__file__).parent / "figures" / "layout_copy.png")
    print(f"{'condition':>17}  {'strides':>18}  {'C':>5}  {'F':>5}  {'median (ms)':>12}  {'slowdown':>9}")
    for row in summary:
        print(
            f"{row['condition']:>17}  {row['strides_bytes']:>18}  "
            f"{str(row['c_contiguous']):>5}  {str(row['f_contiguous']):>5}  "
            f"{float(row['median_seconds']) * 1000:>12.3f}  "
            f"{float(row['slowdown_vs_contiguous']):>8.2f}x"
        )


if __name__ == "__main__":
    main()
