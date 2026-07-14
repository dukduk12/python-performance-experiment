from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import random
import sys

import numpy as np

MODULE_PATH = Path(__file__).parents[1] / "experiments" / "exp05_data_type_element_size" / "benchmark.py"
SPEC = spec_from_file_location("exp05_benchmark", MODULE_PATH)
assert SPEC and SPEC.loader
benchmark = module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def test_arrays_use_requested_dtype_and_equal_values() -> None:
    for dtype_name in benchmark.DTYPE_NAMES:
        source, destination = benchmark.make_arrays(31, dtype_name)
        assert source.dtype == np.dtype(dtype_name)
        assert source.nbytes == 31 * np.dtype(dtype_name).itemsize
        np.copyto(destination, source)
        assert np.array_equal(source, destination)


def test_summary_reports_all_dtype_metrics() -> None:
    measurements = benchmark.benchmark_dtypes(
        1000, repeats=3, warmups=0, rng=random.Random(1)
    )
    rows = benchmark.summarize(measurements)
    assert len(measurements) == 15
    assert [row["dtype"] for row in rows] == list(benchmark.DTYPE_NAMES)
    assert all(row["runs"] == 3 for row in rows)
    assert all(row["array_bytes"] == 1000 * row["itemsize_bytes"] for row in rows)
    assert all(row["allocated_bytes"] == 2 * row["array_bytes"] for row in rows)
    assert all(row["throughput_melements_s"] > 0 for row in rows)
    assert all(row["effective_bandwidth_gib_s"] > 0 for row in rows)
