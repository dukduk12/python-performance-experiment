from importlib import import_module
from pathlib import Path
import random
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1]))
benchmark = import_module("experiments.exp17_memory_copy_vs_view.benchmark")


def test_copy_is_independent_and_views_share_memory() -> None:
    source = benchmark.create_source(4)
    copied = benchmark.create_result(source, "copy")
    sliced = benchmark.create_result(source, "slice_view")
    viewed = benchmark.create_result(source, "ndarray_view")
    assert not np.shares_memory(source, copied)
    assert np.shares_memory(source, sliced)
    assert np.shares_memory(source, viewed)
    source[0, 0] = -1
    assert copied[0, 0] != -1
    assert sliced[0, 0] == viewed[0, 0] == -1


def test_benchmark_covers_sizes_and_conditions() -> None:
    measurements = benchmark.benchmark_operations(
        sizes=(4, 8), repeats=2, warmups=0, rng=random.Random(1)
    )
    summary = benchmark.summarize(measurements)
    assert len(measurements) == 12
    assert len(summary) == 6
    assert all(float(row["median_seconds"]) > 0 for row in summary)
    assert all(float(row["median_traced_peak_bytes"]) > 0 for row in summary)
    copy_rows = [row for row in summary if row["condition"] == "copy"]
    assert all(row["owns_data"] is True for row in copy_rows)
    assert all(row["shares_memory"] is False for row in copy_rows)
