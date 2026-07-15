from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import random
import sys

import numpy as np

MODULE_PATH = Path(__file__).parents[1] / "experiments" / "exp06_contiguous_vs_non_contiguous" / "benchmark.py"
SPEC = spec_from_file_location("exp06_benchmark", MODULE_PATH)
assert SPEC and SPEC.loader
benchmark = module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def test_arrays_have_equal_shapes_and_expected_layouts() -> None:
    arrays = benchmark.make_arrays(7, 11)
    assert all(array.shape == (7, 11) for array in arrays.values())
    assert arrays["contiguous"].flags.c_contiguous
    assert not arrays["sliced_view"].flags.c_contiguous
    assert not arrays["sliced_view"].flags.f_contiguous
    assert arrays["transposed_view"].flags.f_contiguous
    assert arrays["sliced_view"].strides[1] == 2 * np.dtype(np.float64).itemsize


def test_summary_reports_layout_metrics() -> None:
    measurements = benchmark.benchmark_layouts(
        20, 30, repeats=3, warmups=0, rng=random.Random(1)
    )
    rows = benchmark.summarize(measurements)
    assert len(measurements) == 9
    assert [row["condition"] for row in rows] == list(benchmark.CONDITIONS)
    assert all(row["runs"] == 3 for row in rows)
    assert all(row["median_seconds"] > 0 for row in rows)
    assert all(row["throughput_melements_s"] > 0 for row in rows)
    assert rows[0]["slowdown_vs_contiguous"] == 1.0
