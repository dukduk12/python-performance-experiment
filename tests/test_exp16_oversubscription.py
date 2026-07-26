from importlib import import_module
from pathlib import Path
import random
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1]))
benchmark = import_module("experiments.exp16_oversubscription.benchmark")


def test_worker_and_blas_conditions_produce_matching_results() -> None:
    left, right, destinations = benchmark.create_matrices(2, 12, 1)
    one = benchmark.run_condition(left, right, destinations, 1, 1, 1)
    many = benchmark.run_condition(left, right, destinations, 1, 2, 2)
    assert np.allclose(one, many)


def test_benchmark_and_summary_cover_cartesian_product() -> None:
    measurements = benchmark.benchmark_conditions(
        python_workers=(1, 2),
        blas_threads=(1, 2),
        tasks=2,
        matrix_size=12,
        kernel_iterations=1,
        repeats=2,
        warmups=0,
        seed=1,
        rng=random.Random(1),
    )
    summary = benchmark.summarize(measurements)
    assert len(measurements) == 8
    assert [
        (row["python_workers"], row["blas_threads"]) for row in summary
    ] == [(1, 1), (1, 2), (2, 1), (2, 2)]
    assert summary[0]["speedup_vs_1x1"] == 1.0
    assert all(float(row["median_seconds"]) > 0 for row in summary)
    assert all(float(row["median_total_context_switches"]) >= 0 for row in summary)
