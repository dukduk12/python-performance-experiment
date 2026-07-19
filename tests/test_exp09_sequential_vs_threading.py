from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import random
import sys


MODULE_PATH = (
    Path(__file__).parents[1]
    / "experiments"
    / "exp09_sequential_vs_threading"
    / "benchmark.py"
)
SPEC = spec_from_file_location("exp09_benchmark", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
benchmark = module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def test_sequential_and_threaded_results_are_equivalent() -> None:
    seeds = (1, 2, 3, 4)
    expected = benchmark.run_sequential(1_000, seeds)
    assert benchmark.run_threaded(1_000, seeds, 2) == expected
    assert benchmark.run_threaded(1_000, seeds, 4) == expected


def test_benchmark_covers_methods_and_summary_metrics() -> None:
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
    assert all(float(row["median_cpu_utilization_percent"]) >= 0 for row in summary)
