"""Measure how NumPy BLAS thread count affects matrix multiplication."""

from __future__ import annotations

import argparse
import csv
import gc
import json
import os
import platform
import random
import statistics
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_info, threadpool_limits  # type: ignore[import-untyped]

DEFAULT_THREAD_COUNTS = (1, 2, 4, 8)
Scalar = float | int | str


@dataclass(frozen=True)
class Measurement:
    blas_threads: int
    repeat: int
    run_order: int
    matrix_size: int
    kernel_iterations: int
    seconds: float
    process_cpu_seconds: float
    cpu_utilization_percent: float
    checksum: float


def create_matrices(matrix_size: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    return (
        rng.standard_normal((matrix_size, matrix_size), dtype=np.float64),
        rng.standard_normal((matrix_size, matrix_size), dtype=np.float64),
    )


def matrix_multiply(
    left: np.ndarray, right: np.ndarray, destination: np.ndarray, iterations: int
) -> float:
    for _ in range(iterations):
        np.matmul(left, right, out=destination)
    return float(np.sum(destination))


def run_condition(
    left: np.ndarray,
    right: np.ndarray,
    destination: np.ndarray,
    iterations: int,
    blas_threads: int,
) -> float:
    with threadpool_limits(limits=blas_threads, user_api="blas"):
        return matrix_multiply(left, right, destination, iterations)


def benchmark_thread_counts(
    thread_counts: Sequence[int],
    matrix_size: int,
    kernel_iterations: int,
    repeats: int,
    warmups: int,
    seed: int,
    rng: random.Random,
) -> list[Measurement]:
    if not thread_counts or any(count <= 0 for count in thread_counts):
        raise ValueError("thread counts must be positive")
    left, right = create_matrices(matrix_size, seed)
    destination = np.empty_like(left)

    with threadpool_limits(limits=1, user_api="blas"):
        expected = matrix_multiply(left, right, destination, kernel_iterations)
    for count in thread_counts:
        for _ in range(warmups):
            actual = run_condition(
                left, right, destination, kernel_iterations, count
            )
            if not np.isclose(actual, expected, rtol=1e-10, atol=1e-8):
                raise AssertionError(f"{count}-thread result differs")

    measurements: list[Measurement] = []
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        for repeat in range(1, repeats + 1):
            scheduled = list(thread_counts)
            rng.shuffle(scheduled)
            for run_order, count in enumerate(scheduled, start=1):
                cpu_start = time.process_time()
                wall_start = time.perf_counter()
                checksum = run_condition(
                    left, right, destination, kernel_iterations, count
                )
                seconds = time.perf_counter() - wall_start
                cpu_seconds = max(0.0, time.process_time() - cpu_start)
                if not np.isclose(checksum, expected, rtol=1e-10, atol=1e-8):
                    raise AssertionError(f"{count}-thread result differs")
                measurements.append(
                    Measurement(
                        blas_threads=count,
                        repeat=repeat,
                        run_order=run_order,
                        matrix_size=matrix_size,
                        kernel_iterations=kernel_iterations,
                        seconds=seconds,
                        process_cpu_seconds=cpu_seconds,
                        cpu_utilization_percent=100.0 * cpu_seconds / seconds,
                        checksum=checksum,
                    )
                )
    finally:
        if gc_was_enabled:
            gc.enable()
    return measurements


def summarize(measurements: Sequence[Measurement]) -> list[dict[str, Scalar]]:
    one_thread = [item.seconds for item in measurements if item.blas_threads == 1]
    if not one_thread:
        raise ValueError("measurements must include the one-thread baseline")
    baseline = statistics.median(one_thread)
    rows: list[dict[str, Scalar]] = []
    for count in sorted({item.blas_threads for item in measurements}):
        selected = [item for item in measurements if item.blas_threads == count]
        times = [item.seconds for item in selected]
        median = statistics.median(times)
        rows.append(
            {
                "blas_threads": count,
                "runs": len(selected),
                "median_seconds": median,
                "mean_seconds": statistics.fmean(times),
                "stdev_seconds": statistics.stdev(times)
                if len(times) > 1
                else 0.0,
                "speedup_vs_one_thread": baseline / median,
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

    threads = [int(row["blas_threads"]) for row in summary]
    path.parent.mkdir(parents=True, exist_ok=True)
    figure, axes = plt.subplots(1, 3, figsize=(12.5, 4.2))
    axes[0].plot(
        threads,
        [float(row["median_seconds"]) for row in summary],
        marker="o",
    )
    axes[0].set(title="Execution time", xlabel="BLAS threads", ylabel="Median (s)")
    axes[1].plot(
        threads,
        [float(row["speedup_vs_one_thread"]) for row in summary],
        marker="o",
        color="tab:orange",
    )
    axes[1].plot(threads, threads, linestyle="--", color="gray", label="Ideal")
    axes[1].set(title="Speedup", xlabel="BLAS threads", ylabel="Speedup")
    axes[1].legend()
    axes[2].plot(
        threads,
        [float(row["median_cpu_utilization_percent"]) for row in summary],
        marker="o",
        color="tab:green",
    )
    axes[2].axhline(100.0, color="black", linewidth=1)
    axes[2].set(
        title="Process CPU utilization",
        xlabel="BLAS threads",
        ylabel="One-core units (%)",
    )
    for axis in axes:
        axis.set_xticks(threads)
        axis.grid(alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--threads", type=int, nargs="+", default=list(DEFAULT_THREAD_COUNTS)
    )
    parser.add_argument("--matrix-size", type=int, default=2048)
    parser.add_argument("--kernel-iterations", type=int, default=3)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260725)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument(
        "--output-dir", type=Path, default=Path(__file__).parent / "results"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    matrix_size = 128 if args.quick else args.matrix_size
    kernel_iterations = 1 if args.quick else args.kernel_iterations
    repeats = 3 if args.quick else args.repeats
    warmups = 0 if args.quick else args.warmups
    if (
        min(args.threads) <= 0
        or matrix_size <= 0
        or kernel_iterations <= 0
        or repeats <= 0
        or warmups < 0
    ):
        raise SystemExit("counts and sizes must be positive; warmups cannot be negative")
    pools = [pool for pool in threadpool_info() if pool.get("user_api") == "blas"]
    if not pools:
        raise SystemExit("No BLAS thread pool was detected")
    measurements = benchmark_thread_counts(
        args.threads,
        matrix_size,
        kernel_iterations,
        repeats,
        warmups,
        args.seed,
        random.Random(args.seed),
    )
    summary = summarize(measurements)
    write_csv(args.output_dir / "raw.csv", [asdict(item) for item in measurements])
    write_csv(args.output_dir / "summary.csv", summary)
    metadata = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "platform": platform.platform(),
        "logical_cpu_count": os.cpu_count(),
        "blas_thread_pools": pools,
        "thread_counts": args.threads,
        "matrix_size": matrix_size,
        "dtype": "float64",
        "kernel": "numpy.matmul(left, right, out=destination)",
        "kernel_iterations": kernel_iterations,
        "repeats": repeats,
        "warmups": warmups,
        "seed": args.seed,
        "condition_order_randomized": True,
        "gc_disabled_during_measurement": True,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    plot_summary(summary, Path(__file__).parent / "figures" / "blas_threading.png")
    print(f"{'threads':>7}  {'median (s)':>12}  {'speedup':>9}  {'CPU use':>9}")
    for row in summary:
        print(
            f"{int(row['blas_threads']):>7}  "
            f"{float(row['median_seconds']):>12.4f}  "
            f"{float(row['speedup_vs_one_thread']):>8.2f}x  "
            f"{float(row['median_cpu_utilization_percent']):>8.1f}%"
        )


if __name__ == "__main__":
    main()
