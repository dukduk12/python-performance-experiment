"""Measure when CPU task size outweighs multiprocessing overhead."""

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

METHODS = ("sequential", "processes")
DEFAULT_TASK_SIZES = (1_000, 10_000, 100_000, 1_000_000)
Scalar = float | int | str


@dataclass(frozen=True)
class Measurement:
    task_size: int
    method: str
    repeat: int
    run_order: int
    tasks: int
    workers: int
    seconds: float
    checksum: int


def cpu_bound_task(arguments: tuple[int, int]) -> int:
    iterations, seed = arguments
    value = seed & 0xFFFFFFFF
    total = 0
    for index in range(iterations):
        value = (value * 1_664_525 + 1_013_904_223) & 0xFFFFFFFF
        total = (total + (value ^ index)) & 0xFFFFFFFFFFFFFFFF
    return total


def run_sequential(task_size: int, seeds: Sequence[int]) -> list[int]:
    return [cpu_bound_task((task_size, seed)) for seed in seeds]


def run_processes(task_size: int, seeds: Sequence[int], workers: int) -> list[int]:
    arguments = ((task_size, seed) for seed in seeds)
    with ProcessPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(cpu_bound_task, arguments))


def benchmark_task_sizes(
    task_sizes: Sequence[int],
    tasks: int,
    workers: int,
    repeats: int,
    warmups: int,
    rng: random.Random,
) -> list[Measurement]:
    seeds = tuple(range(1, tasks + 1))
    measurements: list[Measurement] = []
    for task_size in task_sizes:
        expected = run_sequential(task_size, seeds)
        functions = {
            "sequential": lambda size=task_size: run_sequential(size, seeds),
            "processes": lambda size=task_size: run_processes(size, seeds, workers),
        }
        for method, function in functions.items():
            if function() != expected:
                raise AssertionError(f"{method} produced a different result")
            for _ in range(warmups):
                function()

        gc_was_enabled = gc.isenabled()
        gc.disable()
        try:
            for repeat in range(1, repeats + 1):
                scheduled = list(METHODS)
                rng.shuffle(scheduled)
                for run_order, method in enumerate(scheduled, start=1):
                    start = time.perf_counter()
                    results = functions[method]()
                    seconds = time.perf_counter() - start
                    if results != expected:
                        raise AssertionError(f"{method} produced a different result")
                    measurements.append(
                        Measurement(
                            task_size=task_size,
                            method=method,
                            repeat=repeat,
                            run_order=run_order,
                            tasks=tasks,
                            workers=workers,
                            seconds=seconds,
                            checksum=sum(expected) & 0xFFFFFFFFFFFFFFFF,
                        )
                    )
        finally:
            if gc_was_enabled:
                gc.enable()
    return measurements


def summarize(measurements: Sequence[Measurement]) -> list[dict[str, Scalar]]:
    rows: list[dict[str, Scalar]] = []
    for task_size in sorted({item.task_size for item in measurements}):
        selected = [item for item in measurements if item.task_size == task_size]
        sequential_times = [
            item.seconds for item in selected if item.method == "sequential"
        ]
        process_times = [
            item.seconds for item in selected if item.method == "processes"
        ]
        if not sequential_times or not process_times:
            continue
        sequential_median = statistics.median(sequential_times)
        process_median = statistics.median(process_times)
        delta = process_median - sequential_median
        rows.append(
            {
                "task_size": task_size,
                "tasks": selected[0].tasks,
                "workers": selected[0].workers,
                "runs_per_method": len(sequential_times),
                "sequential_median_seconds": sequential_median,
                "process_median_seconds": process_median,
                "process_minus_sequential_seconds": delta,
                "speedup": sequential_median / process_median,
                "process_time_share_percent": 100.0
                * process_median
                / sequential_median,
            }
        )
    return rows


def find_break_even(summary: Sequence[Mapping[str, Scalar]]) -> int | None:
    for row in sorted(summary, key=lambda item: int(item["task_size"])):
        if float(row["speedup"]) >= 1.0:
            return int(row["task_size"])
    return None


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

    sizes = [int(row["task_size"]) for row in summary]
    path.parent.mkdir(parents=True, exist_ok=True)
    figure, axes = plt.subplots(1, 2, figsize=(10.5, 4.2))
    axes[0].plot(
        sizes,
        [float(row["sequential_median_seconds"]) for row in summary],
        marker="o",
        label="Sequential",
    )
    axes[0].plot(
        sizes,
        [float(row["process_median_seconds"]) for row in summary],
        marker="o",
        label="4 processes",
    )
    axes[0].set(
        xscale="log",
        yscale="log",
        xlabel="Iterations per task",
        ylabel="Median time (s)",
        title="Execution time",
    )
    axes[0].legend()
    axes[1].plot(
        sizes,
        [float(row["speedup"]) for row in summary],
        marker="o",
        color="tab:orange",
    )
    axes[1].axhline(1.0, color="black", linewidth=1)
    axes[1].set(
        xscale="log",
        xlabel="Iterations per task",
        ylabel="Sequential / processes",
        title="Multiprocessing speedup",
    )
    for axis in axes:
        axis.grid(alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-sizes", type=int, nargs="+", default=DEFAULT_TASK_SIZES)
    parser.add_argument("--tasks", type=int, default=8)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260721)
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Use small task sizes, three repeats, and no warmup",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path(__file__).parent / "results"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    task_sizes = (100, 1_000, 10_000) if args.quick else tuple(args.task_sizes)
    repeats = 3 if args.quick else args.repeats
    warmups = 0 if args.quick else args.warmups
    if (
        any(size <= 0 for size in task_sizes)
        or args.tasks <= 0
        or args.workers <= 0
        or repeats <= 0
        or warmups < 0
    ):
        raise SystemExit(
            "task sizes, tasks, workers, and repeats must be positive; warmups cannot be negative"
        )
    measurements = benchmark_task_sizes(
        task_sizes, args.tasks, args.workers, repeats, warmups, random.Random(args.seed)
    )
    summary = summarize(measurements)
    break_even = find_break_even(summary)
    write_csv(args.output_dir / "raw.csv", [asdict(item) for item in measurements])
    write_csv(args.output_dir / "summary.csv", summary)
    metadata = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "psutil": psutil.__version__,
        "platform": platform.platform(),
        "logical_cpu_count": psutil.cpu_count(logical=True),
        "physical_cpu_count": psutil.cpu_count(logical=False),
        "task_sizes": list(task_sizes),
        "tasks": args.tasks,
        "workers": args.workers,
        "repeats": repeats,
        "warmups": warmups,
        "seed": args.seed,
        "break_even_task_size_in_measured_set": break_even,
        "executor_lifecycle_included": True,
        "gc_disabled_during_measurement": True,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    plot_summary(summary, Path(__file__).parent / "figures" / "task_size_overhead.png")
    print(
        f"{'task size':>12}  {'sequential':>12}  {'processes':>12}  {'delta':>12}  {'speedup':>9}"
    )
    for row in summary:
        print(
            f"{int(row['task_size']):>12,}  {float(row['sequential_median_seconds']):>12.4f}  {float(row['process_median_seconds']):>12.4f}  {float(row['process_minus_sequential_seconds']):>+12.4f}  {float(row['speedup']):>8.2f}x"
        )
    print(
        f"Break-even in measured set: {break_even if break_even is not None else 'not reached'}"
    )


if __name__ == "__main__":
    main()
