"""Traversal kernel executed as the workload of Linux perf stat."""

from __future__ import annotations

import argparse
import json
import statistics
import time

import numpy as np
from numba import njit


@njit(cache=True)
def row_first(array: np.ndarray) -> float:
    total = 0.0
    for row in range(array.shape[0]):
        for column in range(array.shape[1]):
            total += array[row, column]
    return total


@njit(cache=True)
def column_first(array: np.ndarray) -> float:
    total = 0.0
    for column in range(array.shape[1]):
        for row in range(array.shape[0]):
            total += array[row, column]
    return total


def run(condition: str, size: int, iterations: int, warmups: int) -> dict[str, object]:
    array = np.ones((size, size), dtype=np.float64, order="C")
    function = row_first if condition == "row_first" else column_first
    expected = float(size * size)
    for _ in range(warmups):
        if function(array) != expected:
            raise AssertionError("Traversal produced an unexpected sum")

    durations: list[float] = []
    result = 0.0
    for _ in range(iterations):
        start = time.perf_counter()
        result = function(array)
        durations.append(time.perf_counter() - start)
    if result != expected:
        raise AssertionError("Traversal produced an unexpected sum")
    return {
        "condition": condition,
        "size": size,
        "elements": size * size,
        "iterations": iterations,
        "median_seconds": statistics.median(durations),
        "total_timed_seconds": sum(durations),
        "checksum": result,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("condition", choices=("row_first", "column_first"))
    parser.add_argument("--size", type=int, default=4096)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=2)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.size <= 0 or args.iterations <= 0 or args.warmups < 0:
        raise SystemExit("size and iterations must be positive; warmups cannot be negative")
    print(json.dumps(run(args.condition, args.size, args.iterations, args.warmups)))


if __name__ == "__main__":
    main()
