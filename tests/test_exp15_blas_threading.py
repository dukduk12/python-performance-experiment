from importlib import import_module
from pathlib import Path
import random
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1]))
benchmark = import_module("experiments.exp15_blas_threading.benchmark")


def test_thread_conditions_produce_matching_results() -> None:
    left, right = benchmark.create_matrices(16, 1)
    destination = np.empty_like(left)
    one = benchmark.run_condition(left, right, destination, 2, 1)
    two = benchmark.run_condition(left, right, destination, 2, 2)
    assert np.isclose(one, two)


def test_benchmark_and_summary_cover_all_thread_counts() -> None:
    measurements = benchmark.benchmark_thread_counts(
        thread_counts=(1, 2, 4),
        matrix_size=16,
        kernel_iterations=1,
        repeats=2,
        warmups=0,
        seed=1,
        rng=random.Random(1),
    )
    summary = benchmark.summarize(measurements)
    assert len(measurements) == 6
    assert [row["blas_threads"] for row in summary] == [1, 2, 4]
    assert all(float(row["median_seconds"]) > 0 for row in summary)
    assert summary[0]["speedup_vs_one_thread"] == 1.0
