from experiments.exp20_cpython_object_overhead import benchmark as b


def test_object_accounting():
    rows = b.measure(100)
    assert rows[0]["total_bytes"] > rows[1]["total_bytes"]
    assert all(float(x["bytes_per_element"]) > 0 for x in rows)
