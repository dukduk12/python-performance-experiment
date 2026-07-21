"""Compare sequential and threaded execution for CPU- and I/O-bound tasks."""

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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

import psutil

WORKLOADS = ("cpu", "io")
METHODS = ("sequential", "threaded")
Scalar = float | int | str


@dataclass(frozen=True)
class Measurement:
    workload: str
    method: str
    repeat: int
    run_order: int
    tasks: int
    workers: int
    seconds: float
    process_cpu_seconds: float
    cpu_utilization_percent: float
    checksum: int


def cpu_bound_task(iterations: int, seed: int) -> int:
    value = seed & 0xFFFFFFFF
    total = 0
    for index in range(iterations):
        value = (value * 1_664_525 + 1_013_904_223) & 0xFFFFFFFF
        total = (total + (value ^ index)) & 0xFFFFFFFFFFFFFFFF
    return total


def io_bound_task(delay: float, seed: int) -> int:
    time.sleep(delay)
    return seed


def run_sequential(function: Callable[[int], int], seeds: Sequence[int]) -> list[int]:
    return [function(seed) for seed in seeds]


def run_threaded(
    function: Callable[[int], int], seeds: Sequence[int], workers: int
) -> list[int]:
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(function, seeds))


def benchmark_workloads(
    tasks: int,
    workers: int,
    cpu_iterations: int,
    io_delay: float,
    repeats: int,
    warmups: int,
    rng: random.Random,
) -> list[Measurement]:
    seeds = tuple(range(1, tasks + 1))
    workload_functions: dict[str, Callable[[int], int]] = {
        "cpu": partial(cpu_bound_task, cpu_iterations),
        "io": partial(io_bound_task, io_delay),
    }
    expected = {
        "cpu": [cpu_bound_task(cpu_iterations, seed) for seed in seeds],
        "io": list(seeds),
    }
    conditions: dict[tuple[str, str], Callable[[], list[int]]] = {}
    for workload, task_function in workload_functions.items():
        conditions[(workload, "sequential")] = partial(
            run_sequential, task_function, seeds
        )
        conditions[(workload, "threaded")] = partial(
            run_threaded, task_function, seeds, workers
        )

    for (workload, _), function in conditions.items():
        if function() != expected[workload]:
            raise AssertionError(f"{workload} workload produced a different result")
        for _ in range(warmups):
            function()

    process = psutil.Process()
    measurements: list[Measurement] = []
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        for repeat in range(1, repeats + 1):
            scheduled = list(conditions)
            rng.shuffle(scheduled)
            for run_order, (workload, method) in enumerate(scheduled, start=1):
                cpu_start = sum(process.cpu_times()[:2])
                wall_start = time.perf_counter()
                result = conditions[(workload, method)]()
                seconds = time.perf_counter() - wall_start
                cpu_seconds = max(0.0, sum(process.cpu_times()[:2]) - cpu_start)
                if result != expected[workload]:
                    raise AssertionError(f"{workload}/{method} produced a different result")
                measurements.append(Measurement(
                    workload, method, repeat, run_order, tasks,
                    1 if method == "sequential" else workers,
                    seconds, cpu_seconds, 100.0 * cpu_seconds / seconds,
                    sum(result) & 0xFFFFFFFFFFFFFFFF,
                ))
    finally:
        if gc_was_enabled:
            gc.enable()
    return measurements


def summarize(measurements: Sequence[Measurement]) -> list[dict[str, Scalar]]:
    rows: list[dict[str, Scalar]] = []
    for workload in WORKLOADS:
        sequential = [m.seconds for m in measurements if m.workload == workload and m.method == "sequential"]
        baseline = statistics.median(sequential)
        for method in METHODS:
            selected = [m for m in measurements if m.workload == workload and m.method == method]
            times = [m.seconds for m in selected]
            median = statistics.median(times)
            rows.append({
                "workload": workload,
                "method": method,
                "workers": selected[0].workers,
                "runs": len(selected),
                "median_seconds": median,
                "mean_seconds": statistics.fmean(times),
                "stdev_seconds": statistics.stdev(times) if len(times) > 1 else 0.0,
                "median_cpu_utilization_percent": statistics.median(m.cpu_utilization_percent for m in selected),
                "speedup_vs_sequential": baseline / median,
            })
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

    labels = [f"{row['workload']}\n{row['method']}" for row in summary]
    path.parent.mkdir(parents=True, exist_ok=True)
    figure, axes = plt.subplots(1, 3, figsize=(13, 4.3))
    axes[0].bar(labels, [float(row["median_seconds"]) for row in summary])
    axes[0].set(title="Execution time", ylabel="Median time (s)")
    axes[1].bar(labels, [float(row["speedup_vs_sequential"]) for row in summary], color="tab:orange")
    axes[1].axhline(1.0, color="black", linewidth=1)
    axes[1].set(title="Threading speedup", ylabel="Speedup vs sequential")
    axes[2].bar(labels, [float(row["median_cpu_utilization_percent"]) for row in summary], color="tab:green")
    axes[2].set(title="Process CPU use", ylabel="One-core utilization (%)")
    for axis in axes:
        axis.grid(axis="y", alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=int, default=8)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--cpu-iterations", type=int, default=1_000_000)
    parser.add_argument("--io-delay", type=float, default=0.2)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260722)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "results")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tasks = 4 if args.quick else args.tasks
    cpu_iterations = 20_000 if args.quick else args.cpu_iterations
    io_delay = 0.01 if args.quick else args.io_delay
    repeats = 3 if args.quick else args.repeats
    warmups = 0 if args.quick else args.warmups
    if min(tasks, args.workers, cpu_iterations, repeats) <= 0 or io_delay < 0 or warmups < 0:
        raise SystemExit("counts must be positive; delay and warmups cannot be negative")
    measurements = benchmark_workloads(tasks, args.workers, cpu_iterations, io_delay, repeats, warmups, random.Random(args.seed))
    summary = summarize(measurements)
    write_csv(args.output_dir / "raw.csv", [asdict(item) for item in measurements])
    write_csv(args.output_dir / "summary.csv", summary)
    metadata = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(), "python": sys.version,
        "psutil": psutil.__version__, "platform": platform.platform(),
        "logical_cpu_count": psutil.cpu_count(logical=True), "physical_cpu_count": psutil.cpu_count(logical=False),
        "tasks": tasks, "workers": args.workers, "cpu_iterations": cpu_iterations,
        "io_delay_seconds": io_delay, "repeats": repeats, "warmups": warmups,
        "seed": args.seed, "timer": "time.perf_counter",
        "io_model": "time.sleep (reproducible waiting surrogate)",
        "cpu_measurement": "process CPU time / wall time * 100", "gc_disabled_during_measurement": True,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    plot_summary(summary, Path(__file__).parent / "figures" / "cpu_vs_io_bound.png")
    print(f"{'workload':>8}  {'method':>10}  {'median (s)':>12}  {'speedup':>9}  {'CPU use':>10}")
    for row in summary:
        print(f"{row['workload']:>8}  {row['method']:>10}  {float(row['median_seconds']):>12.4f}  {float(row['speedup_vs_sequential']):>8.2f}x  {float(row['median_cpu_utilization_percent']):>9.1f}%")


if __name__ == "__main__":
    main()
