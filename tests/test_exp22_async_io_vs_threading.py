from experiments.exp22_async_io_vs_threading import benchmark as b


def test_io_conditions():
    rows = b.run(2, 0.0001, 2, 1)
    assert {x["condition"] for x in rows} == {"sequential", "threading", "asyncio"}
    assert all(x["seconds"] > 0 for x in rows)
