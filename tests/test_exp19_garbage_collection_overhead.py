from experiments.exp19_garbage_collection_overhead import benchmark as b


def test_gc_benchmark():
    rows = b.run(100, 2, 0)
    assert len(rows) == 4 and len({x.checksum for x in rows}) == 1
    assert {x.condition for x in rows} == {"enabled", "disabled"}
