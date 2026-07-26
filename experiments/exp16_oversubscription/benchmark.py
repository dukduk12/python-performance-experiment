"""Measure oversubscription from combining Python workers and BLAS threads."""

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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import psutil
from threadpoolctl import threadpool_info, threadpool_limits  # type: ignore[import-untyped]

DEFAULT_PYTHON_WORKERS = (1, 2, 4, 8)
DEFAULT_BLAS_THREADS = (1, 2, 4, 8)
Scalar = float | int | str


@dataclass(frozen=True)
class Measurement:
    python_workers: int
    blas_threads: int
    native_thread_budget: int
    repeat: int
    run_order: int
    tasks: int
    matrix_size: int
    kernel_iterations: int
    seconds: float
    process_cpu_seconds: float
    cpu_utilization_percent: float
    voluntary_context_switches: int
    involuntary_context_switches: int
    total_context_switches: int
    checksum: float


def create_matrices(
    tasks: int, matrix_size: int, seed: int
) -> tuple[list[np.ndarray], list[np.ndarray], list[np.ndarray]]:
    rng = np.random.default_rng(seed)
    left = [
        rng.standard_normal((matrix_size, matrix_size), dtype=np.float64)
        for _ in range(tasks)
    ]
    right = [
        rng.standard_normal((matrix_size, matrix_size), dtype=np.float64)
        for _ in range(tasks)
    ]
    destinations = [np.empty_like(matrix) for matrix in left]
    return left, right, destinations


def matrix_task(
    left: np.ndarray,
    right: np.ndarray,
    destination: np.ndarray,
    kernel_iterations: int,
) -> float:
    for _ in range(kernel_iterations):
        np.matmul(left, right, out=destination)
    return float(np.sum(destination))


def run_condition(
    left: Sequence[np.ndarray],
    right: Sequence[np.ndarray],
    destinations: Sequence[np.ndarray],
    kernel_iterations: int,
    python_workers: int,
    blas_threads: int,
) -> list[float]:
    with threadpool_limits(limits=blas_threads, user_api="blas"):
        with ThreadPoolExecutor(max_workers=python_workers) as executor:
            futures = [
                executor.submit(matrix_task, a, b, out, kernel_iterations)
                for a, b, out in zip(left, right, destinations, strict=True)
            ]
            return [future.result() for future in futures]


def benchmark_conditions(
    python_workers: Sequence[int],
    blas_threads: Sequence[int],
    tasks: int,
    matrix_size: int,
    kernel_iterations: int,
    repeats: int,
    warmups: int,
    seed: int,
    rng: random.Random,
) -> list[Measurement]:
    if (
        not python_workers
        or not blas_threads
        or any(value <= 0 for value in (*python_workers, *blas_threads))
    ):
        raise ValueError("worker and BLAS thread counts must be positive")
    left, right, destinations = create_matrices(tasks, matrix_size, seed)
    conditions = [(workers, threads) for workers in python_workers for threads in blas_threads]
    expected = run_condition(
        left, right, destinations, kernel_iterations, 1, 1
    )
    for workers, threads in conditions:
        for _ in range(warmups):
            actual = run_condition(
                left, right, destinations, kernel_iterations, workers, threads
            )
            if not np.allclose(actual, expected, rtol=1e-10, atol=1e-8):
                raise AssertionError(f"{workers}x{threads} result differs")

    process = psutil.Process()
    measurements: list[Measurement] = []
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        for repeat in range(1, repeats + 1):
            scheduled = list(conditions)
            rng.shuffle(scheduled)
            for run_order, (workers, threads) in enumerate(scheduled, start=1):
                switches_start = process.num_ctx_switches()
                cpu_start = time.process_time()
                wall_start = time.perf_counter()
                result = run_condition(
                    left, right, destinations, kernel_iterations, workers, threads
                )
                seconds = time.perf_counter() - wall_start
                cpu_seconds = max(0.0, time.process_time() - cpu_start)
                switches_end = process.num_ctx_switches()
                if not np.allclose(result, expected, rtol=1e-10, atol=1e-8):
                    raise AssertionError(f"{workers}x{threads} result differs")
                voluntary = max(0, switches_end.voluntary - switches_start.voluntary)
                involuntary = max(
                    0, switches_end.involuntary - switches_start.involuntary
                )
                measurements.append(
                    Measurement(
                        python_workers=workers,
                        blas_threads=threads,
                        native_thread_budget=workers * threads,
                        repeat=repeat,
                        run_order=run_order,
                        tasks=tasks,
                        matrix_size=matrix_size,
                        kernel_iterations=kernel_iterations,
                        seconds=seconds,
                        process_cpu_seconds=cpu_seconds,
                        cpu_utilization_percent=100.0 * cpu_seconds / seconds,
                        voluntary_context_switches=voluntary,
                        involuntary_context_switches=involuntary,
                        total_context_switches=voluntary + involuntary,
                        checksum=float(sum(result)),
                    )
                )
    finally:
        if gc_was_enabled:
            gc.enable()
    return measurements


def summarize(measurements: Sequence[Measurement]) -> list[dict[str, Scalar]]:
    baseline_times = [
        item.seconds
        for item in measurements
        if item.python_workers == 1 and item.blas_threads == 1
    ]
    if not baseline_times:
        raise ValueError("measurements must include the 1x1 baseline")
    baseline = statistics.median(baseline_times)
    pairs = sorted(
        {(item.python_workers, item.blas_threads) for item in measurements}
    )
    rows: list[dict[str, Scalar]] = []
    for workers, threads in pairs:
        selected = [
            item
            for item in measurements
            if item.python_workers == workers and item.blas_threads == threads
        ]
        times = [item.seconds for item in selected]
        median = statistics.median(times)
        rows.append(
            {
                "python_workers": workers,
                "blas_threads": threads,
                "native_thread_budget": workers * threads,
                "runs": len(selected),
                "median_seconds": median,
                "mean_seconds": statistics.fmean(times),
                "stdev_seconds": statistics.stdev(times) if len(times) > 1 else 0.0,
                "speedup_vs_1x1": baseline / median,
                "median_cpu_utilization_percent": statistics.median(
                    item.cpu_utilization_percent for item in selected
                ),
                "median_total_context_switches": statistics.median(
                    item.total_context_switches for item in selected
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

    workers = sorted({int(row["python_workers"]) for row in summary})
    threads = sorted({int(row["blas_threads"]) for row in summary})
    lookup = {
        (int(row["python_workers"]), int(row["blas_threads"])): row
        for row in summary
    }
    figure, axes = plt.subplots(1, 3, figsize=(13, 4.2))
    for blas in threads:
        axes[0].plot(
            workers,
            [float(lookup[(worker, blas)]["median_seconds"]) for worker in workers],
            marker="o",
            label=f"BLAS {blas}",
        )
        axes[1].plot(
            workers,
            [
                float(lookup[(worker, blas)]["median_cpu_utilization_percent"])
                for worker in workers
            ],
            marker="o",
            label=f"BLAS {blas}",
        )
        axes[2].plot(
            workers,
            [
                float(lookup[(worker, blas)]["median_total_context_switches"])
                for worker in workers
            ],
            marker="o",
            label=f"BLAS {blas}",
        )
    axes[0].set(title="Execution time", ylabel="Median (s)")
    axes[1].set(title="Process CPU utilization", ylabel="One-core units (%)")
    axes[2].set(title="Context switches", ylabel="Median count")
    for axis in axes:
        axis.set_xlabel("Python workers")
        axis.set_xticks(workers)
        axis.grid(alpha=0.3)
        axis.legend()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--python-workers", type=int, nargs="+", default=list(DEFAULT_PYTHON_WORKERS)
    )
    parser.add_argument(
        "--blas-threads", type=int, nargs="+", default=list(DEFAULT_BLAS_THREADS)
    )
    parser.add_argument("--tasks", type=int, default=8)
    parser.add_argument("--matrix-size", type=int, default=1024)
    parser.add_argument("--kernel-iterations", type=int, default=2)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260726)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument(
        "--output-dir", type=Path, default=Path(__file__).parent / "results"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    matrix_size = 96 if args.quick else args.matrix_size
    kernel_iterations = 1 if args.quick else args.kernel_iterations
    repeats = 2 if args.quick else args.repeats
    warmups = 0 if args.quick else args.warmups
    if (
        min(
            *args.python_workers,
            *args.blas_threads,
            args.tasks,
            matrix_size,
            kernel_iterations,
            repeats,
        )
        <= 0
        or warmups < 0
    ):
        raise SystemExit("counts and sizes must be positive; warmups cannot be negative")
    pools = [pool for pool in threadpool_info() if pool.get("user_api") == "blas"]
    if not pools:
        raise SystemExit("No BLAS thread pool was detected")
    measurements = benchmark_conditions(
        args.python_workers,
        args.blas_threads,
        args.tasks,
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
        "psutil": psutil.__version__,
        "platform": platform.platform(),
        "logical_cpu_count": os.cpu_count(),
        "blas_thread_pools": pools,
        "python_workers": args.python_workers,
        "blas_threads": args.blas_threads,
        "tasks": args.tasks,
        "matrix_size": matrix_size,
        "dtype": "float64",
        "kernel": "numpy.matmul(left, right, out=destination)",
        "kernel_iterations": kernel_iterations,
        "repeats": repeats,
        "warmups": warmups,
        "seed": args.seed,
        "condition_order_randomized": True,
        "executor_lifecycle_included": True,
        "gc_disabled_during_measurement": True,
        "context_switch_scope": "current process as reported by psutil",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    plot_summary(summary, Path(__file__).parent / "figures" / "oversubscription.png")
    print(
        f"{'workers':>7}  {'BLAS':>4}  {'budget':>6}  {'median (s)':>12}  "
        f"{'speedup':>8}  {'CPU use':>9}  {'ctx sw':>7}"
    )
    for row in summary:
        print(
            f"{int(row['python_workers']):>7}  {int(row['blas_threads']):>4}  "
            f"{int(row['native_thread_budget']):>6}  "
            f"{float(row['median_seconds']):>12.4f}  "
            f"{float(row['speedup_vs_1x1']):>7.2f}x  "
            f"{float(row['median_cpu_utilization_percent']):>8.1f}%  "
            f"{float(row['median_total_context_switches']):>7.1f}"
        )


if __name__ == "__main__":
    main()
