from importlib import import_module
from pathlib import Path
import random
import sys


sys.path.insert(0, str(Path(__file__).parents[1]))
benchmark = import_module(
    "experiments.exp10_sequential_vs_multiprocessing.benchmark"
)


def test_sequential_and_process_results_are_equivalent() -> None:
    seeds = (1, 2, 3, 4)
    expected = benchmark.checksums(benchmark.run_sequential(1_000, seeds))
    assert benchmark.checksums(benchmark.run_processes(1_000, seeds, 2)) == expected
    assert benchmark.checksums(benchmark.run_processes(1_000, seeds, 4)) == expected


def test_benchmark_covers_methods_and_scaling_metrics() -> None:
    measurements = benchmark.benchmark_methods(
        tasks=4,
        iterations=1_000,
        repeats=3,
        warmups=0,
        rng=random.Random(1),
    )
    summary = benchmark.summarize(measurements)
    assert [row["method"] for row in summary] == list(benchmark.METHODS)
    assert len(measurements) == 9
    assert all(float(row["median_seconds"]) > 0 for row in summary)
    assert summary[0]["speedup_vs_sequential"] == 1.0
    assert summary[0]["scaling_efficiency"] == 1.0
    assert all(float(row["scaling_efficiency"]) > 0 for row in summary)
