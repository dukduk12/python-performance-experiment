"""Compare sequential execution with processes for a CPU-bound Python workload."""

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
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import psutil

METHODS = ("sequential", "processes_2", "processes_4")
Scalar = float | int | str


@dataclass(frozen=True)
class TaskResult:
    checksum: int
    cpu_seconds: float


@dataclass(frozen=True)
class Measurement:
    method: str
    repeat: int
    run_order: int
    tasks: int
    iterations_per_task: int
    seconds: float
    aggregate_cpu_seconds: float
    cpu_utilization_percent: float
    checksum: int


def cpu_bound_task(iterations: int, seed: int) -> TaskResult:
    """Run deterministic Python integer work and report this task's CPU time."""
    cpu_start = time.process_time()
    value = seed & 0xFFFFFFFF
    total = 0
    for index in range(iterations):
        value = (value * 1_664_525 + 1_013_904_223) & 0xFFFFFFFF
        total = (total + (value ^ index)) & 0xFFFFFFFFFFFFFFFF
    return TaskResult(total, time.process_time() - cpu_start)


def run_sequential(iterations: int, seeds: Sequence[int]) -> list[TaskResult]:
    return [cpu_bound_task(iterations, seed) for seed in seeds]


def run_processes(
    iterations: int, seeds: Sequence[int], workers: int
) -> list[TaskResult]:
    arguments = ((iterations, seed) for seed in seeds)
    with ProcessPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(_run_task, arguments))


def _run_task(arguments: tuple[int, int]) -> TaskResult:
    return cpu_bound_task(*arguments)


def checksums(results: Sequence[TaskResult]) -> list[int]:
    return [result.checksum for result in results]


def functions_for(
    iterations: int, seeds: Sequence[int]
) -> dict[str, Callable[[], list[TaskResult]]]:
    return {
        "sequential": lambda: run_sequential(iterations, seeds),
        "processes_2": lambda: run_processes(iterations, seeds, 2),
        "processes_4": lambda: run_processes(iterations, seeds, 4),
    }


def benchmark_methods(
    tasks: int,
    iterations: int,
    repeats: int,
    warmups: int,
    rng: random.Random,
) -> list[Measurement]:
    seeds = tuple(range(1, tasks + 1))
    functions = functions_for(iterations, seeds)
    expected = checksums(run_sequential(iterations, seeds))
    for method, function in functions.items():
        if checksums(function()) != expected:
            raise AssertionError(f"{method} produced a different result")
    for function in functions.values():
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
                wall_start = time.perf_counter()
                results = functions[method]()
                seconds = time.perf_counter() - wall_start
                if checksums(results) != expected:
                    raise AssertionError(f"{method} produced a different result")
                cpu_seconds = sum(result.cpu_seconds for result in results)
                measurements.append(
                    Measurement(
                        method=method,
                        repeat=repeat,
                        run_order=run_order,
                        tasks=tasks,
                        iterations_per_task=iterations,
                        seconds=seconds,
                        aggregate_cpu_seconds=cpu_seconds,
                        cpu_utilization_percent=100.0 * cpu_seconds / seconds,
                        checksum=sum(expected) & 0xFFFFFFFFFFFFFFFF,
                    )
                )
    finally:
        if gc_was_enabled:
            gc.enable()
    return measurements


def summarize(measurements: Sequence[Measurement]) -> list[dict[str, Scalar]]:
    sequential_median = statistics.median(
        item.seconds for item in measurements if item.method == "sequential"
    )
    rows: list[dict[str, Scalar]] = []
    for method in METHODS:
        selected = [item for item in measurements if item.method == method]
        if not selected:
            continue
        workers = 1 if method == "sequential" else int(method[-1])
        times = [item.seconds for item in selected]
        median = statistics.median(times)
        speedup = sequential_median / median
        rows.append(
            {
                "method": method,
                "workers": workers,
                "runs": len(selected),
                "tasks": selected[0].tasks,
                "iterations_per_task": selected[0].iterations_per_task,
                "median_seconds": median,
                "mean_seconds": statistics.fmean(times),
                "stdev_seconds": statistics.stdev(times) if len(times) > 1 else 0.0,
                "median_aggregate_cpu_seconds": statistics.median(
                    item.aggregate_cpu_seconds for item in selected
                ),
                "median_cpu_utilization_percent": statistics.median(
                    item.cpu_utilization_percent for item in selected
                ),
                "speedup_vs_sequential": speedup,
                "scaling_efficiency": speedup / workers,
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

    labels = [str(row["method"]).replace("_", "\n") for row in summary]
    path.parent.mkdir(parents=True, exist_ok=True)
    figure, axes = plt.subplots(1, 3, figsize=(13, 4.3))
    axes[0].bar(labels, [float(row["median_seconds"]) for row in summary])
    axes[0].set(title="Execution time", ylabel="Median time (s)")
    axes[1].bar(
        labels,
        [float(row["speedup_vs_sequential"]) for row in summary],
        color="tab:orange",
    )
    axes[1].axhline(1.0, color="black", linewidth=1)
    axes[1].set(title="Speedup", ylabel="Speedup vs sequential")
    axes[2].bar(
        labels,
        [100.0 * float(row["scaling_efficiency"]) for row in summary],
        color="tab:green",
    )
    axes[2].axhline(100.0, color="black", linewidth=1)
    axes[2].set(title="Scaling efficiency", ylabel="Efficiency (%)")
    for axis in axes:
        axis.grid(axis="y", alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=int, default=8)
    parser.add_argument("--iterations", type=int, default=1_000_000)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260720)
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Use four short tasks, three repeats, and no warmup",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path(__file__).parent / "results"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tasks = 4 if args.quick else args.tasks
    iterations = 20_000 if args.quick else args.iterations
    repeats = 3 if args.quick else args.repeats
    warmups = 0 if args.quick else args.warmups
    if tasks <= 0 or iterations <= 0 or repeats <= 0 or warmups < 0:
        raise SystemExit(
            "tasks, iterations and repeats must be positive; warmups cannot be negative"
        )
    measurements = benchmark_methods(
        tasks, iterations, repeats, warmups, random.Random(args.seed)
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
        "tasks": tasks,
        "iterations_per_task": iterations,
        "repeats": repeats,
        "warmups": warmups,
        "seed": args.seed,
        "timer": "time.perf_counter",
        "cpu_measurement": "sum of task time.process_time / wall time * 100",
        "executor_lifecycle_included": True,
        "gc_disabled_during_measurement": True,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    plot_summary(summary, Path(__file__).parent / "figures" / "multiprocessing.png")
    print(
        f"{'method':>12}  {'median (s)':>12}  {'speedup':>9}  {'efficiency':>11}"
    )
    for row in summary:
        print(
            f"{row['method']:>12}  {float(row['median_seconds']):>12.3f}  "
            f"{float(row['speedup_vs_sequential']):>8.2f}x  "
            f"{100.0 * float(row['scaling_efficiency']):>10.1f}%"
        )


if __name__ == "__main__":
    main()
