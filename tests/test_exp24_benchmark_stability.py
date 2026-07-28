import random
from experiments.exp24_benchmark_stability import benchmark as b


def test_stability_summary():
    rows = b.collect("randomized", 3, 10, random.Random(1))
    out = b.summarize(rows, [3])
    assert len(rows) == 6 and len(out) == 2 and all(x["sample_count"] == 3 for x in out)
