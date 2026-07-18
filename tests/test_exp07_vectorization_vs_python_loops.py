from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import random
import sys

import numpy as np

MODULE_PATH = (
    Path(__file__).parents[1]
    / "experiments"
    / "exp07_vectorization_vs_python_loops"
    / "benchmark.py"
)
SPEC = spec_from_file_location("exp07_benchmark", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
benchmark = module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def test_implementations_are_equivalent() -> None:
    python_values, numpy_values = benchmark.make_inputs(31)
    actual = benchmark.python_loop(python_values)
    expected = benchmark.numpy_vectorized(numpy_values)
    assert np.allclose(actual, expected)


def test_benchmark_covers_methods_and_summary_metrics() -> None:
    measurements = benchmark.benchmark_methods(
        100, repeats=3, warmups=0, rng=random.Random(1)
    )
    summary = benchmark.summarize(
        measurements, {"python_loop": 123, "numpy_vectorized": 45}
    )
    assert [row["method"] for row in summary] == list(benchmark.METHODS)
    assert len(measurements) == 6
    assert all(float(row["median_seconds"]) > 0 for row in summary)
    assert summary[0]["speedup_vs_python"] == 1.0
    assert [row["peak_traced_bytes"] for row in summary] == [123, 45]
