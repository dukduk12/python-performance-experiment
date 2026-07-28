from experiments.exp25_cpu_warmup_frequency_scaling import benchmark as b


def test_warmup_sequence():
    rows = b.run(100, 3)
    assert [x["phase"] for x in rows] == ["cold", "warm", "warm"]
    assert len({x["checksum"] for x in rows}) == 1
