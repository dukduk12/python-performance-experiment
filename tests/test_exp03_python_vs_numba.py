from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import random
import sys

import numpy as np

MODULE_PATH = (
    Path(__file__).parents[1] / "experiments" / "exp03_python_vs_numba" / "benchmark.py"
)
SPEC = spec_from_file_location("exp03_benchmark", MODULE_PATH)
assert SPEC and SPEC.loader
benchmark = module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def test_all_implementations_return_the_same_checksum() -> None:
    array = benchmark.make_array(7)
    expected = int(np.arange(49, dtype=np.int64).sum())
    assert array.flags.c_contiguous
    assert all(function(array) == expected for function in benchmark.FUNCTIONS.values())


def test_benchmark_covers_all_conditions_and_ratios() -> None:
    measurements = benchmark.benchmark_size(
        8, repeats=3, warmups=0, rng=random.Random(1)
    )
    rows = benchmark.summarize(measurements)
    assert len(measurements) == 12
    assert len(rows) == 4
    assert all(row["runs"] == 3 for row in rows)
    assert all(row["speedup_vs_python"] > 0 for row in rows)
    assert all(row["column_vs_row_slowdown"] > 0 for row in rows)
    assert all(
        row["speedup_vs_python"] == 1.0 for row in rows if row["engine"] == "python"
    )
