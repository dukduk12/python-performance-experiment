from importlib import import_module
from pathlib import Path
import random
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1]))
benchmark = import_module("experiments.exp14_numpy_and_gil.benchmark")


def test_sequential_and_threaded_results_match() -> None:
    sources, destinations = benchmark.create_buffers(4, 100)
    sequential = benchmark.run_sequential(sources, destinations, 2)
    threaded = benchmark.run_threaded(sources, destinations, 2, 2)
    assert np.allclose(sequential, threaded)


def test_benchmark_and_summary_cover_both_methods() -> None:
    measurements = benchmark.benchmark_methods(
        tasks=4,
        workers=2,
        array_size=100,
        kernel_iterations=2,
        repeats=2,
        warmups=0,
        rng=random.Random(1),
    )
    summary = benchmark.summarize(measurements)
    assert len(measurements) == 4
    assert [row["method"] for row in summary] == ["sequential", "threaded"]
    assert all(float(row["median_seconds"]) > 0 for row in summary)
    assert all(float(row["speedup_vs_sequential"]) > 0 for row in summary)
    assert summary[0]["speedup_vs_sequential"] == 1.0
