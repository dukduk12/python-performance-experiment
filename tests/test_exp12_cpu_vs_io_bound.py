from importlib import import_module
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
benchmark = import_module("experiments.exp12_cpu_vs_io_bound.benchmark")


def test_cpu_and_io_results_match_between_methods() -> None:
    seeds = (1, 2, 3, 4)

    def cpu(seed: int) -> int:
        return benchmark.cpu_bound_task(100, seed)

    def io(seed: int) -> int:
        return benchmark.io_bound_task(0, seed)

    assert benchmark.run_sequential(cpu, seeds) == benchmark.run_threaded(cpu, seeds, 2)
    assert benchmark.run_sequential(io, seeds) == benchmark.run_threaded(io, seeds, 2)


def test_benchmark_covers_both_workloads_and_methods() -> None:
    measurements = benchmark.benchmark_workloads(4, 2, 100, 0.001, 2, 0, random.Random(1))
    summary = benchmark.summarize(measurements)
    assert len(measurements) == 8
    assert [(row["workload"], row["method"]) for row in summary] == [
        ("cpu", "sequential"), ("cpu", "threaded"),
        ("io", "sequential"), ("io", "threaded"),
    ]
    assert all(float(row["median_seconds"]) > 0 for row in summary)
    assert all(float(row["speedup_vs_sequential"]) > 0 for row in summary)
