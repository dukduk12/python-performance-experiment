from experiments.exp21_pypy_vs_cpython import benchmark as b


def test_interpreter_runner():
    interpreters = b.available_interpreters()
    assert "cpython" in interpreters
    rows = b.run({"cpython": interpreters["cpython"]}, 100, 2)
    assert len(rows) == 2
    assert len({x["checksum"] for x in rows}) == 1
