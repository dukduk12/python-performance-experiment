from __future__ import annotations

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

MODULE_PATH = (
    Path(__file__).parents[1]
    / "experiments"
    / "exp08_cache_miss_measurement"
    / "benchmark.py"
)
SPEC = spec_from_file_location("exp08_benchmark", MODULE_PATH)
assert SPEC and SPEC.loader
benchmark = module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def test_parse_perf_csv_extracts_requested_events() -> None:
    output = (
        "1,234;;cache-references;100.00;100.00;;\n"
        "56;;cache-misses;100.00;100.00;;\n"
    )
    assert benchmark.parse_perf_csv(output) == {
        "cache-references": 1234,
        "cache-misses": 56,
    }


def test_summary_calculates_miss_rate_and_slowdown() -> None:
    measurements = [
        benchmark.Measurement("row_first", 1, 1, 1.0, 2.0, 100, 10, 10.0),
        benchmark.Measurement("row_first", 2, 2, 1.2, 2.4, 120, 12, 10.0),
        benchmark.Measurement("column_first", 1, 2, 2.0, 4.0, 100, 30, 30.0),
        benchmark.Measurement("column_first", 2, 1, 2.4, 4.8, 120, 36, 30.0),
    ]
    rows = benchmark.summarize(measurements)
    assert [row["condition"] for row in rows] == list(benchmark.CONDITIONS)
    assert rows[0]["median_miss_rate_percent"] == 10.0
    assert rows[1]["slowdown_vs_row"] == 2.0
