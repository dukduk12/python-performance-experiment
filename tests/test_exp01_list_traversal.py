from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


MODULE_PATH = Path(__file__).parents[1] / "experiments" / "exp01_list_traversal" / "benchmark.py"
SPEC = spec_from_file_location("benchmark", MODULE_PATH)
assert SPEC and SPEC.loader
benchmark = module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def test_traversals_return_same_checksum() -> None:
    matrix = benchmark.make_matrix(17)
    assert benchmark.traverse_rows(matrix) == benchmark.traverse_columns(matrix)


def test_summary_has_required_statistics() -> None:
    import random

    measurements = benchmark.benchmark_size(8, repeats=3, warmups=0, rng=random.Random(1))
    rows = benchmark.summarize(measurements)
    assert len(rows) == 2
    assert all(row["runs"] == 3 for row in rows)
    assert all("median_seconds" in row and "stdev_seconds" in row for row in rows)
