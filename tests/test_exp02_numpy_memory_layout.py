from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import random
import sys

import numpy as np

MODULE_PATH = Path(__file__).parents[1] / "experiments" / "exp02_numpy_memory_layout" / "benchmark.py"
SPEC = spec_from_file_location("exp02_benchmark", MODULE_PATH)
assert SPEC and SPEC.loader
benchmark = module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def test_arrays_have_expected_layout_and_checksum() -> None:
    arrays = benchmark.make_arrays(7)
    assert arrays["C"].flags.c_contiguous and arrays["F"].flags.f_contiguous
    assert arrays["C"].strides == (7 * np.dtype(np.int64).itemsize, np.dtype(np.int64).itemsize)
    assert arrays["F"].strides == (np.dtype(np.int64).itemsize, 7 * np.dtype(np.int64).itemsize)
    assert benchmark.traverse_rows(arrays["C"]) == benchmark.traverse_columns(arrays["F"])


def test_benchmark_covers_four_conditions_and_statistics() -> None:
    measurements = benchmark.benchmark_size(8, repeats=3, warmups=0, rng=random.Random(1))
    rows = benchmark.summarize(measurements)
    assert len(measurements) == 12
    assert len(rows) == 4
    assert all(row["runs"] == 3 for row in rows)
    assert all("slowdown_vs_matched" in row and "median_seconds" in row for row in rows)
