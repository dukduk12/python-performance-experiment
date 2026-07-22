"""Measure CPU-bound process-pool scaling as worker count increases."""

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
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import psutil

DEFAULT_WORKERS = (1, 2, 4, 8)
Scalar = float | int | str


@dataclass(frozen=True)
class TaskResult:
    checksum: int
    cpu_seconds: float
    voluntary_context_switches: int
    involuntary_context_switches: int


@dataclass(frozen=True)
class Measurement:
    workers: int
    repeat: int
    run_order: int
    tasks: int
    iterations_per_task: int
    seconds: float
    worker_cpu_seconds: float
    cpu_utilization_percent: float
    voluntary_context_switches: int
    involuntary_context_switches: int
    context_switches: int
    checksum: int


def cpu_bound_task(iterations: int, seed: int) -> TaskResult:
    process = psutil.Process()
    cpu_start = sum(process.cpu_times()[:2])
    switches_start = process.num_ctx_switches()
    value = seed & 0xFFFFFFFF
    total = 0
    for index in range(iterations):
        value = (value * 1_664_525 + 1_013_904_223) & 0xFFFFFFFF
        total = (total + (value ^ index)) & 0xFFFFFFFFFFFFFFFF
    switches_end = process.num_ctx_switches()
    cpu_seconds = max(0.0, sum(process.cpu_times()[:2]) - cpu_start)
    return TaskResult(
        checksum=total,
        cpu_seconds=cpu_seconds,
        voluntary_context_switches=max(
            0, switches_end.voluntary - switches_start.voluntary
        ),
        involuntary_context_switches=max(
            0, switches_end.involuntary - switches_start.involuntary
        ),
    )


def run_process_pool(
    tasks: int, iterations_per_task: int, workers: int
) -> list[TaskResult]:
    iterations = [iterations_per_task] * tasks
    seeds = list(range(1, tasks + 1))
    with ProcessPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(cpu_bound_task, iterations, seeds))


def benchmark_worker_counts(
    worker_counts: Sequence[int],
    tasks: int,
    iterations_per_task: int,
    repeats: int,
    warmups: int,
    rng: random.Random,
) -> list[Measurement]:
    expected = [
        cpu_bound_task(iterations_per_task, seed).checksum
        for seed in range(1, tasks + 1)
    ]
    for workers in worker_counts:
        for _ in range(warmups):
            results = run_process_pool(tasks, iterations_per_task, workers)
            if [result.checksum for result in results] != expected:
                raise AssertionError(
                    f"{workers}-worker run produced a different result"
                )

    measurements: list[Measurement] = []
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        for repeat in range(1, repeats + 1):
            scheduled = list(worker_counts)
            rng.shuffle(scheduled)
            for run_order, workers in enumerate(scheduled, start=1):
                wall_start = time.perf_counter()
                results = run_process_pool(tasks, iterations_per_task, workers)
                seconds = time.perf_counter() - wall_start
                checksums = [result.checksum for result in results]
                if checksums != expected:
                    raise AssertionError(
                        f"{workers}-worker run produced a different result"
                    )
                cpu_seconds = sum(result.cpu_seconds for result in results)
                voluntary = sum(result.voluntary_context_switches for result in results)
                involuntary = sum(
                    result.involuntary_context_switches for result in results
                )
                measurements.append(
                    Measurement(
                        workers=workers,
                        repeat=repeat,
                        run_order=run_order,
                        tasks=tasks,
                        iterations_per_task=iterations_per_task,
                        seconds=seconds,
                        worker_cpu_seconds=cpu_seconds,
                        cpu_utilization_percent=100.0 * cpu_seconds / seconds,
                        voluntary_context_switches=voluntary,
                        involuntary_context_switches=involuntary,
                        context_switches=voluntary + involuntary,
                        checksum=sum(checksums) & 0xFFFFFFFFFFFFFFFF,
                    )
                )
    finally:
        if gc_was_enabled:
            gc.enable()
    return measurements


def summarize(measurements: Sequence[Measurement]) -> list[dict[str, Scalar]]:
    baseline_times = [item.seconds for item in measurements if item.workers == 1]
    if not baseline_times:
        raise ValueError("measurements must include a one-worker baseline")
    baseline = statistics.median(baseline_times)
    rows: list[dict[str, Scalar]] = []
    for workers in sorted({item.workers for item in measurements}):
        selected = [item for item in measurements if item.workers == workers]
        times = [item.seconds for item in selected]
        median = statistics.median(times)
        speedup = baseline / median
        rows.append(
            {
                "workers": workers,
                "runs": len(selected),
                "median_seconds": median,
                "mean_seconds": statistics.fmean(times),
                "stdev_seconds": statistics.stdev(times) if len(times) > 1 else 0.0,
                "speedup_vs_one_worker": speedup,
                "scaling_efficiency_percent": 100.0 * speedup / workers,
                "median_cpu_utilization_percent": statistics.median(
                    item.cpu_utilization_percent for item in selected
                ),
                "median_context_switches": statistics.median(
                    item.context_switches for item in selected
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

    workers = [int(row["workers"]) for row in summary]
    path.parent.mkdir(parents=True, exist_ok=True)
    figure, axes = plt.subplots(1, 3, figsize=(13, 4.3))
    axes[0].plot(workers, [float(row["median_seconds"]) for row in summary], marker="o")
    axes[0].set(title="Execution time", xlabel="Workers", ylabel="Median time (s)")
    speedups = [float(row["speedup_vs_one_worker"]) for row in summary]
    axes[1].plot(workers, speedups, marker="o", label="Measured")
    axes[1].plot(workers, workers, linestyle="--", color="gray", label="Ideal")
    axes[1].set(title="Process-pool speedup", xlabel="Workers", ylabel="Speedup")
    axes[1].legend()
    axes[2].bar(
        [str(value) for value in workers],
        [float(row["median_context_switches"]) for row in summary],
    )
    axes[2].set(
        title="Worker context switches", xlabel="Workers", ylabel="Median count"
    )
    for axis in axes:
        axis.grid(axis="y", alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def parse_worker_counts(value: str) -> tuple[int, ...]:
    try:
        counts = tuple(int(item.strip()) for item in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "workers must be comma-separated integers"
        ) from error
    if (
        not counts
        or any(count <= 0 for count in counts)
        or len(set(counts)) != len(counts)
    ):
        raise argparse.ArgumentTypeError(
            "worker counts must be unique positive integers"
        )
    if 1 not in counts:
        raise argparse.ArgumentTypeError("worker counts must include 1 as the baseline")
    return counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=parse_worker_counts, default=DEFAULT_WORKERS)
    parser.add_argument("--tasks", type=int, default=16)
    parser.add_argument("--iterations", type=int, default=1_000_000)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260723)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument(
        "--output-dir", type=Path, default=Path(__file__).parent / "results"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tasks = 8 if args.quick else args.tasks
    iterations = 20_000 if args.quick else args.iterations
    repeats = 3 if args.quick else args.repeats
    warmups = 0 if args.quick else args.warmups
    if min(tasks, iterations, repeats) <= 0 or warmups < 0:
        raise SystemExit(
            "tasks, iterations, and repeats must be positive; warmups cannot be negative"
        )
    measurements = benchmark_worker_counts(
        args.workers, tasks, iterations, repeats, warmups, random.Random(args.seed)
    )
    summary = summarize(measurements)
    write_csv(args.output_dir / "raw.csv", [asdict(item) for item in measurements])
    write_csv(args.output_dir / "summary.csv", summary)
    metadata = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "psutil": psutil.__version__,
        "platform": platform.platform(),
        "logical_cpu_count": psutil.cpu_count(logical=True),
        "physical_cpu_count": psutil.cpu_count(logical=False),
        "worker_counts": args.workers,
        "tasks": tasks,
        "iterations_per_task": iterations,
        "repeats": repeats,
        "warmups": warmups,
        "seed": args.seed,
        "timer": "time.perf_counter",
        "context_switch_measurement": "sum of per-task worker process deltas",
        "gc_disabled_in_parent_during_measurement": True,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    plot_summary(
        summary, Path(__file__).parent / "figures" / "worker_count_scaling.png"
    )
    print(
        f"{'workers':>7}  {'median (s)':>12}  {'speedup':>9}  {'efficiency':>11}  {'ctx switches':>12}"
    )
    for row in summary:
        print(
            f"{int(row['workers']):>7}  {float(row['median_seconds']):>12.4f}  {float(row['speedup_vs_one_worker']):>8.2f}x  {float(row['scaling_efficiency_percent']):>10.1f}%  {float(row['median_context_switches']):>12.0f}"
        )


if __name__ == "__main__":
    main()
