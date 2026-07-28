from experiments.exp23_false_sharing import benchmark as b


def test_shared_writes():
    rows = b.run(2, 10, 1)
    assert len(rows) == 2
    assert len({x["checksum"] for x in rows}) == 1
