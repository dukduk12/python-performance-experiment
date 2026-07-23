"""Compare sequential and threaded execution of independent NumPy ufunc tasks."""

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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

METHODS = ("sequential", "threaded")
Scalar = float | int | str


@dataclass(frozen=True)
class Measurement:
    method: str
    repeat: int
    run_order: int
    tasks: int
    workers: int
    array_size: int
    kernel_iterations: int
    seconds: float
    process_cpu_seconds: float
    cpu_utilization_percent: float
    checksum: float


def numpy_task(
    source: np.ndarray, destination: np.ndarray, kernel_iterations: int
) -> float:
    """Run a native NumPy ufunc repeatedly without allocating timed temporaries."""
    for _ in range(kernel_iterations):
        np.sin(source, out=destination)
    return float(np.sum(destination))


def create_buffers(
    tasks: int, array_size: int
) -> tuple[list[np.ndarray], list[np.ndarray]]:
    base = np.linspace(-3.0, 3.0, array_size, dtype=np.float64)
    sources = [base + task * 0.001 for task in range(tasks)]
    destinations = [np.empty_like(base) for _ in range(tasks)]
    return sources, destinations


def run_sequential(
    sources: Sequence[np.ndarray],
    destinations: Sequence[np.ndarray],
    kernel_iterations: int,
) -> list[float]:
    return [
        numpy_task(source, destination, kernel_iterations)
        for source, destination in zip(sources, destinations, strict=True)
    ]


def run_threaded(
    sources: Sequence[np.ndarray],
    destinations: Sequence[np.ndarray],
    kernel_iterations: int,
    workers: int,
) -> list[float]:
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(numpy_task, source, destination, kernel_iterations)
            for source, destination in zip(sources, destinations, strict=True)
        ]
        return [future.result() for future in futures]


def benchmark_methods(
    tasks: int,
    workers: int,
    array_size: int,
    kernel_iterations: int,
    repeats: int,
    warmups: int,
    rng: random.Random,
) -> list[Measurement]:
    sources, destinations = create_buffers(tasks, array_size)
    expected = run_sequential(sources, destinations, kernel_iterations)
    conditions = {
        "sequential": lambda: run_sequential(
            sources, destinations, kernel_iterations
        ),
        "threaded": lambda: run_threaded(
            sources, destinations, kernel_iterations, workers
        ),
    }
    for method, function in conditions.items():
        if not np.allclose(function(), expected, rtol=1e-12, atol=1e-12):
            raise AssertionError(f"{method} run produced a different result")
        for _ in range(warmups):
            function()

    measurements: list[Measurement] = []
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        for repeat in range(1, repeats + 1):
            scheduled = list(METHODS)
            rng.shuffle(scheduled)
            for run_order, method in enumerate(scheduled, start=1):
                cpu_start = time.process_time()
                wall_start = time.perf_counter()
                result = conditions[method]()
                seconds = time.perf_counter() - wall_start
                cpu_seconds = max(0.0, time.process_time() - cpu_start)
                if not np.allclose(result, expected, rtol=1e-12, atol=1e-12):
                    raise AssertionError(f"{method} run produced a different result")
                measurements.append(
                    Measurement(
                        method=method,
                        repeat=repeat,
                        run_order=run_order,
                        tasks=tasks,
                        workers=1 if method == "sequential" else workers,
                        array_size=array_size,
                        kernel_iterations=kernel_iterations,
                        seconds=seconds,
                        process_cpu_seconds=cpu_seconds,
                        cpu_utilization_percent=100.0 * cpu_seconds / seconds,
                        checksum=float(sum(result)),
                    )
                )
    finally:
        if gc_was_enabled:
            gc.enable()
    return measurements


def summarize(measurements: Sequence[Measurement]) -> list[dict[str, Scalar]]:
    baseline_times = [
        item.seconds for item in measurements if item.method == "sequential"
    ]
    if not baseline_times:
        raise ValueError("measurements must include the sequential baseline")
    baseline = statistics.median(baseline_times)
    rows: list[dict[str, Scalar]] = []
    for method in METHODS:
        selected = [item for item in measurements if item.method == method]
        if not selected:
            raise ValueError(f"measurements must include {method}")
        times = [item.seconds for item in selected]
        median = statistics.median(times)
        rows.append(
            {
                "method": method,
                "workers": selected[0].workers,
                "runs": len(selected),
                "median_seconds": median,
                "mean_seconds": statistics.fmean(times),
                "stdev_seconds": statistics.stdev(times)
                if len(times) > 1
                else 0.0,
                "speedup_vs_sequential": baseline / median,
                "median_cpu_utilization_percent": statistics.median(
                    item.cpu_utilization_percent for item in selected
                ),
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

    labels = [str(row["method"]).title() for row in summary]
    path.parent.mkdir(parents=True, exist_ok=True)
    figure, axes = plt.subplots(1, 3, figsize=(12.5, 4.2))
    axes[0].bar(labels, [float(row["median_seconds"]) for row in summary])
    axes[0].set(title="Execution time", ylabel="Median time (s)")
    axes[1].bar(
        labels,
        [float(row["speedup_vs_sequential"]) for row in summary],
        color="tab:orange",
    )
    axes[1].axhline(1.0, color="black", linewidth=1)
    axes[1].set(title="Threading speedup", ylabel="Speedup")
    axes[2].bar(
        labels,
        [float(row["median_cpu_utilization_percent"]) for row in summary],
        color="tab:green",
    )
    axes[2].axhline(100.0, color="black", linewidth=1)
    axes[2].set(title="Process CPU utilization", ylabel="One-core units (%)")
    for axis in axes:
        axis.grid(axis="y", alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=int, default=8)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--array-size", type=int, default=1_000_000)
    parser.add_argument("--kernel-iterations", type=int, default=8)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260724)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument(
        "--output-dir", type=Path, default=Path(__file__).parent / "results"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tasks = 4 if args.quick else args.tasks
    array_size = 10_000 if args.quick else args.array_size
    kernel_iterations = 2 if args.quick else args.kernel_iterations
    repeats = 3 if args.quick else args.repeats
    warmups = 0 if args.quick else args.warmups
    if min(
        tasks,
        args.workers,
        array_size,
        kernel_iterations,
        repeats,
    ) <= 0 or warmups < 0:
        raise SystemExit("counts and sizes must be positive; warmups cannot be negative")
    measurements = benchmark_methods(
        tasks,
        args.workers,
        array_size,
        kernel_iterations,
        repeats,
        warmups,
        random.Random(args.seed),
    )
    summary = summarize(measurements)
    write_csv(args.output_dir / "raw.csv", [asdict(item) for item in measurements])
    write_csv(args.output_dir / "summary.csv", summary)
    is_gil_enabled = getattr(sys, "_is_gil_enabled", None)
    metadata = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "numpy": np.__version__,
        "platform": platform.platform(),
        "logical_cpu_count": os.cpu_count(),
        "gil_enabled": is_gil_enabled() if is_gil_enabled is not None else "unknown",
        "tasks": tasks,
        "workers": args.workers,
        "array_size": array_size,
        "dtype": "float64",
        "kernel": "numpy.sin(source, out=destination)",
        "kernel_iterations": kernel_iterations,
        "repeats": repeats,
        "warmups": warmups,
        "seed": args.seed,
        "timers": ["time.perf_counter", "time.process_time"],
        "executor_lifecycle_included": True,
        "gc_disabled_during_measurement": True,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    plot_summary(summary, Path(__file__).parent / "figures" / "numpy_and_gil.png")
    print(
        f"{'method':>10}  {'median (s)':>12}  {'speedup':>9}  {'CPU use':>9}"
    )
    for row in summary:
        print(
            f"{str(row['method']):>10}  "
            f"{float(row['median_seconds']):>12.4f}  "
            f"{float(row['speedup_vs_sequential']):>8.2f}x  "
            f"{float(row['median_cpu_utilization_percent']):>8.1f}%"
        )


if __name__ == "__main__":
    main()
