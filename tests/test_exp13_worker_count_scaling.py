from importlib import import_module
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
benchmark = import_module("experiments.exp13_worker_count_scaling.benchmark")


def test_process_pool_preserves_results_across_worker_counts() -> None:
    one_worker = benchmark.run_process_pool(4, 100, 1)
    two_workers = benchmark.run_process_pool(4, 100, 2)
    assert [item.checksum for item in one_worker] == [
        item.checksum for item in two_workers
    ]


def test_benchmark_and_summary_cover_worker_counts() -> None:
    measurements = benchmark.benchmark_worker_counts(
        (1, 2), 4, 100, 2, 0, random.Random(1)
    )
    summary = benchmark.summarize(measurements)
    assert len(measurements) == 4
    assert [row["workers"] for row in summary] == [1, 2]
    assert all(float(row["median_seconds"]) > 0 for row in summary)
    assert all(float(row["speedup_vs_one_worker"]) > 0 for row in summary)
    assert summary[0]["scaling_efficiency_percent"] == 100.0


def test_worker_parser_requires_positive_unique_baseline() -> None:
    assert benchmark.parse_worker_counts("1,2,4,8") == (1, 2, 4, 8)
