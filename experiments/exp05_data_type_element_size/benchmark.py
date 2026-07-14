"""Measure how NumPy element size affects contiguous copy performance."""

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

DTYPE_NAMES = ("int8", "int32", "int64", "float32", "float64")
Scalar = float | int | str


@dataclass(frozen=True)
class Measurement:
    dtype: str
    itemsize_bytes: int
    elements: int
    array_bytes: int
    allocated_bytes: int
    bytes_copied: int
    repeat: int
    run_order: int
    seconds: float


def make_arrays(elements: int, dtype_name: str) -> tuple[NDArray, NDArray]:
    dtype = np.dtype(dtype_name)
    source = np.arange(elements, dtype=dtype)
    destination = np.empty_like(source)
    return source, destination


def benchmark_dtypes(
    elements: int,
    repeats: int,
    warmups: int,
    rng: random.Random,
    dtype_names: Sequence[str] = DTYPE_NAMES,
) -> list[Measurement]:
    arrays = {name: make_arrays(elements, name) for name in dtype_names}
    for source, destination in arrays.values():
        np.copyto(destination, source)
        if not np.array_equal(source, destination):
            raise AssertionError("Validation copy did not preserve values")
        for _ in range(warmups):
            np.copyto(destination, source)

    measurements: list[Measurement] = []
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        for repeat in range(1, repeats + 1):
            scheduled = list(dtype_names)
            rng.shuffle(scheduled)
            for run_order, dtype_name in enumerate(scheduled, start=1):
                source, destination = arrays[dtype_name]
                start = time.perf_counter()
                np.copyto(destination, source)
                elapsed = time.perf_counter() - start
                measurements.append(
                    Measurement(
                        dtype_name,
                        int(source.itemsize),
                        int(source.size),
                        int(source.nbytes),
                        int(source.nbytes + destination.nbytes),
                        int(source.nbytes),
                        repeat,
                        run_order,
                        elapsed,
                    )
                )
    finally:
        if gc_was_enabled:
            gc.enable()

    for source, destination in arrays.values():
        if not np.array_equal(source, destination):
            raise AssertionError("Timed copy did not preserve values")
    return measurements


def summarize(measurements: Sequence[Measurement]) -> list[dict[str, Scalar]]:
    rows: list[dict[str, Scalar]] = []
    for dtype_name in DTYPE_NAMES:
        selected = [item for item in measurements if item.dtype == dtype_name]
        if not selected:
            continue
        values = [item.seconds for item in selected]
        median = statistics.median(values)
        sample = selected[0]
        rows.append(
            {
                "dtype": dtype_name,
                "itemsize_bytes": sample.itemsize_bytes,
                "elements": sample.elements,
                "array_bytes": sample.array_bytes,
                "allocated_bytes": sample.allocated_bytes,
                "runs": len(values),
                "mean_seconds": statistics.fmean(values),
                "median_seconds": median,
                "stdev_seconds": statistics.stdev(values) if len(values) > 1 else 0.0,
                "min_seconds": min(values),
                "max_seconds": max(values),
                "throughput_melements_s": sample.elements / median / 1_000_000,
                "effective_bandwidth_gib_s": (2 * sample.bytes_copied) / median / (1024**3),
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

    labels = [str(row["dtype"]) for row in summary]
    path.parent.mkdir(parents=True, exist_ok=True)
    figure, (memory_axis, throughput_axis) = plt.subplots(1, 2, figsize=(11, 4.5))
    memory_axis.bar(labels, [int(row["array_bytes"]) / (1024**2) for row in summary])
    memory_axis.set(title="Memory per array", xlabel="NumPy dtype", ylabel="MiB")
    memory_axis.grid(axis="y", alpha=0.3)

    throughput_axis.bar(
        labels, [float(row["throughput_melements_s"]) for row in summary], color="tab:orange"
    )
    throughput_axis.set(
        title="Contiguous copy throughput",
        xlabel="NumPy dtype",
        ylabel="Million elements/s",
    )
    throughput_axis.grid(axis="y", alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elements", type=int, default=8_000_000)
    parser.add_argument("--repeats", type=int, default=11)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260715)
    parser.add_argument("--quick", action="store_true", help="Use 100,000 elements and three repeats")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "results")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    elements = 100_000 if args.quick else args.elements
    repeats = 3 if args.quick else args.repeats
    if elements <= 0 or repeats <= 0 or args.warmups < 0:
        raise SystemExit("elements and repeats must be positive; warmups cannot be negative")

    measurements = benchmark_dtypes(
        elements, repeats, args.warmups, random.Random(args.seed)
    )
    summary = summarize(measurements)
    write_csv(args.output_dir / "raw.csv", [asdict(item) for item in measurements])
    write_csv(args.output_dir / "summary.csv", summary)
    metadata = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "numpy": np.__version__,
        "platform": platform.platform(),
        "elements": elements,
        "dtypes": list(DTYPE_NAMES),
        "operation": "numpy.copyto",
        "repeats": repeats,
        "warmups": args.warmups,
        "seed": args.seed,
        "timer": "time.perf_counter",
        "allocation_included": False,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    plot_summary(summary, Path(__file__).parent / "figures" / "dtype_element_size.png")

    print(f"{'dtype':>8}  {'bytes':>5}  {'array MiB':>10}  {'median (ms)':>12}  {'M elem/s':>10}  {'GiB/s':>8}")
    for row in summary:
        print(
            f"{row['dtype']:>8}  {row['itemsize_bytes']:>5}  "
            f"{int(row['array_bytes']) / (1024**2):>10.2f}  "
            f"{float(row['median_seconds']) * 1000:>12.3f}  "
            f"{float(row['throughput_melements_s']):>10.1f}  "
            f"{float(row['effective_bandwidth_gib_s']):>8.2f}"
        )


if __name__ == "__main__":
    main()
