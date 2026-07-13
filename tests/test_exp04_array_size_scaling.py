from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import random
import sys

import numpy as np

MODULE_PATH = (
    Path(__file__).parents[1] / "experiments" / "exp04_array_size_scaling" / "benchmark.py"
)
SPEC = spec_from_file_location("exp04_benchmark", MODULE_PATH)
assert SPEC and SPEC.loader
benchmark = module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def test_traversals_return_the_same_checksum() -> None:
    array = benchmark.make_array(7)
    expected = int(np.arange(49, dtype=np.int64).sum())
    assert array.flags.c_contiguous
    assert benchmark.row_first(array) == expected
    assert benchmark.column_first(array) == expected


def test_summary_reports_scaling_metrics_for_both_traversals() -> None:
    measurements = benchmark.benchmark_size(
        8, repeats=3, warmups=0, rng=random.Random(1)
    )
    rows = benchmark.summarize(measurements)
    assert len(measurements) == 6
    assert len(rows) == 2
    assert all(row["runs"] == 3 for row in rows)
    assert all(row["working_set_bytes"] == 8 * 8 * 8 for row in rows)
    assert all(row["throughput_melements_s"] > 0 for row in rows)
    assert all(row["slowdown_vs_row"] > 0 for row in rows)
    assert next(row for row in rows if row["traversal"] == "row_first")[
        "slowdown_vs_row"
    ] == 1.0
