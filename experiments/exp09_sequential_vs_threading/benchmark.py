"""Compare sequential execution with threads for a CPU-bound Python workload."""

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
from pathlib import Path

import psutil

METHODS = ("sequential", "threads_2", "threads_4")
Scalar = float | int | str


@dataclass(frozen=True)
class Measurement:
    method: str
    repeat: int
    run_order: int
    tasks: int
    iterations_per_task: int
    seconds: float
    process_cpu_seconds: float
    cpu_utilization_percent: float
    checksum: int


def cpu_bound_task(iterations: int, seed: int) -> int:
    """Run deterministic Python integer work without calling C extension kernels."""
    value = seed & 0xFFFFFFFF
    total = 0
    for index in range(iterations):
        value = (value * 1_664_525 + 1_013_904_223) & 0xFFFFFFFF
        total = (total + (value ^ index)) & 0xFFFFFFFFFFFFFFFF
    return total


def run_sequential(iterations: int, seeds: Sequence[int]) -> list[int]:
    return [cpu_bound_task(iterations, seed) for seed in seeds]


def run_threaded(iterations: int, seeds: Sequence[int], workers: int) -> list[int]:
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(lambda seed: cpu_bound_task(iterations, seed), seeds))


def functions_for(
    iterations: int, seeds: Sequence[int]
) -> dict[str, Callable[[], list[int]]]:
    return {
        "sequential": lambda: run_sequential(iterations, seeds),
        "threads_2": lambda: run_threaded(iterations, seeds, 2),
        "threads_4": lambda: run_threaded(iterations, seeds, 4),
    }


def process_cpu_time(process: psutil.Process) -> float:
    times = process.cpu_times()
    return float(times.user + times.system)


def benchmark_methods(
    tasks: int,
    iterations: int,
    repeats: int,
    warmups: int,
    rng: random.Random,
) -> list[Measurement]:
    seeds = tuple(range(1, tasks + 1))
    functions = functions_for(iterations, seeds)
    expected = run_sequential(iterations, seeds)
    for method, function in functions.items():
        actual = function()
        if actual != expected:
            raise AssertionError(f"{method} produced a different result")
    for function in functions.values():
        for _ in range(warmups):
            function()

    process = psutil.Process()
    measurements: list[Measurement] = []
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        for repeat in range(1, repeats + 1):
            scheduled = list(METHODS)
            rng.shuffle(scheduled)
            for run_order, method in enumerate(scheduled, start=1):
                cpu_start = process_cpu_time(process)
                wall_start = time.perf_counter()
                result = functions[method]()
                seconds = time.perf_counter() - wall_start
                cpu_seconds = max(0.0, process_cpu_time(process) - cpu_start)
                if result != expected:
                    raise AssertionError(f"{method} produced a different result")
                measurements.append(
                    Measurement(
                        method=method,
                        repeat=repeat,
                        run_order=run_order,
                        tasks=tasks,
                        iterations_per_task=iterations,
                        seconds=seconds,
                        process_cpu_seconds=cpu_seconds,
                        cpu_utilization_percent=100.0 * cpu_seconds / seconds,
                        checksum=sum(result) & 0xFFFFFFFFFFFFFFFF,
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
        times = [item.seconds for item in selected]
        cpu_times = [item.process_cpu_seconds for item in selected]
        utilization = [item.cpu_utilization_percent for item in selected]
        median = statistics.median(times)
        rows.append(
            {
                "method": method,
                "workers": 1 if method == "sequential" else int(method[-1]),
                "runs": len(selected),
                "tasks": selected[0].tasks,
                "iterations_per_task": selected[0].iterations_per_task,
                "median_seconds": median,
                "mean_seconds": statistics.fmean(times),
                "stdev_seconds": statistics.stdev(times) if len(times) > 1 else 0.0,
                "median_process_cpu_seconds": statistics.median(cpu_times),
                "median_cpu_utilization_percent": statistics.median(utilization),
                "speedup_vs_sequential": sequential_median / median,
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
        [float(row["median_cpu_utilization_percent"]) for row in summary],
        color="tab:green",
    )
    axes[2].axhline(100.0, color="black", linewidth=1)
    axes[2].set(title="Process CPU use", ylabel="One-core utilization (%)")
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
    parser.add_argument("--seed", type=int, default=20260719)
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
        "cpu_measurement": "(process user + system CPU time) / wall time * 100",
        "gc_disabled_during_measurement": True,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    plot_summary(summary, Path(__file__).parent / "figures" / "threading.png")
    print(f"{'method':>12}  {'median (s)':>12}  {'speedup':>9}  {'CPU use':>10}")
    for row in summary:
        print(
            f"{row['method']:>12}  {float(row['median_seconds']):>12.3f}  "
            f"{float(row['speedup_vs_sequential']):>8.2f}x  "
            f"{float(row['median_cpu_utilization_percent']):>9.1f}%"
        )


if __name__ == "__main__":
    main()
