from importlib import import_module
from pathlib import Path
import random
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1]))
benchmark = import_module("experiments.exp18_transpose_cost.benchmark")


def test_transpose_view_and_contiguous_copy_semantics() -> None:
    source = benchmark.create_source(4)
    view = benchmark.create_transpose(source, "transpose_view")
    copied = benchmark.create_transpose(source, "contiguous_copy")
    assert np.array_equal(view, source.T)
    assert np.array_equal(copied, source.T)
    assert np.shares_memory(source, view)
    assert not np.shares_memory(source, copied)
    assert view.flags.f_contiguous and not view.flags.c_contiguous
    assert copied.flags.c_contiguous


def test_benchmark_separates_creation_and_traversal() -> None:
    measurements = benchmark.benchmark_operations(
        sizes=(4, 8), repeats=2, warmups=0, rng=random.Random(1)
    )
    summary = benchmark.summarize(measurements)
    assert len(measurements) == 8
    assert len(summary) == 4
    assert all(item.creation_seconds > 0 for item in measurements)
    assert all(item.traversal_seconds > 0 for item in measurements)
    assert {row["condition"] for row in summary} == set(benchmark.CONDITIONS)


def test_unknown_condition_is_rejected() -> None:
    with np.testing.assert_raises(ValueError):
        benchmark.create_transpose(benchmark.create_source(2), "unknown")
