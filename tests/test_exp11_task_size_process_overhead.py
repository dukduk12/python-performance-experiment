from importlib import import_module
from pathlib import Path
import random
import sys


sys.path.insert(0, str(Path(__file__).parents[1]))
benchmark = import_module("experiments.exp11_task_size_process_overhead.benchmark")


def test_sequential_and_process_results_are_equivalent() -> None:
    seeds = (1, 2, 3, 4)
    assert benchmark.run_processes(1_000, seeds, 2) == benchmark.run_sequential(
        1_000, seeds
    )


def test_benchmark_covers_task_sizes_and_metrics() -> None:
    measurements = benchmark.benchmark_task_sizes(
        task_sizes=(100, 1_000),
        tasks=4,
        workers=2,
        repeats=2,
        warmups=0,
        rng=random.Random(1),
    )
    summary = benchmark.summarize(measurements)
    assert len(measurements) == 8
    assert [row["task_size"] for row in summary] == [100, 1_000]
    assert all(float(row["sequential_median_seconds"]) > 0 for row in summary)
    assert all(float(row["process_median_seconds"]) > 0 for row in summary)
    assert all(float(row["speedup"]) > 0 for row in summary)


def test_find_break_even_returns_first_qualifying_size() -> None:
    rows = [
        {"task_size": 100, "speedup": 0.5},
        {"task_size": 1_000, "speedup": 1.1},
        {"task_size": 10_000, "speedup": 2.0},
    ]
    assert benchmark.find_break_even(rows) == 1_000
    assert benchmark.find_break_even(rows[:1]) is None
