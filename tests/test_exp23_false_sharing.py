from experiments.exp23_false_sharing import benchmark as b


def test_shared_writes():
    rows = b.run(2, 10, 1, seed=1)
    assert len(rows) == 2
    assert len({row.checksum for row in rows}) == 1
    assert {row.condition for row in rows} == set(b.CONDITIONS)
    assert {row.run_order for row in rows} == {1, 2}


def test_summary_uses_adjacent_as_baseline():
    rows = [
        b.Measurement("adjacent", 1, 1, 2.0, 4, 10, 8, 36),
        b.Measurement("adjacent", 2, 2, 4.0, 4, 10, 8, 36),
        b.Measurement("separated", 1, 2, 1.0, 4, 10, 128, 36),
        b.Measurement("separated", 2, 1, 3.0, 4, 10, 128, 36),
    ]
    summary = b.summarize(rows)
    assert [row["condition"] for row in summary] == list(b.CONDITIONS)
    assert summary[0]["speedup_vs_adjacent"] == 1.0
    assert summary[1]["speedup_vs_adjacent"] == 1.5


def test_summary_handles_single_condition_run():
    rows = [b.Measurement("separated", 1, 1, 2.0, 4, 10, 128, 36)]
    summary = b.summarize(rows)
    assert summary == [
        {
            "condition": "separated",
            "runs": 1,
            "median_seconds": 2.0,
            "min_seconds": 2.0,
            "max_seconds": 2.0,
            "stdev_seconds": 0.0,
            "speedup_vs_adjacent": 1.0,
            "stride_bytes": 128,
        }
    ]
