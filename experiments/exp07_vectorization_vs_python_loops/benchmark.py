"""Compare a Python element-wise loop with an equivalent NumPy expression."""

from __future__ import annotations

import argparse
import csv
import gc
import json
import os
import platform
import random
import statistics
import sys
import time
import tracemalloc
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

METHODS = ("python_loop", "numpy_vectorized")
Scalar = float | int | str
Result = list[float] | NDArray[np.float64]


@dataclass(frozen=True)
class Measurement:
    method: str
    elements: int
    repeat: int
    run_order: int
    seconds: float


def python_loop(values: list[float]) -> list[float]:
    """Evaluate y = x*x + 3*x element by element in CPython."""
    output = [0.0] * len(values)
    for index, value in enumerate(values):
        output[index] = value * value + 3.0 * value
    return output


def numpy_vectorized(values: NDArray[np.float64]) -> NDArray[np.float64]:
    """Evaluate the same expression with NumPy array operations."""
    return values * values + 3.0 * values


def make_inputs(elements: int) -> tuple[list[float], NDArray[np.float64]]:
    """Create equivalent Python-list and ndarray inputs outside timed regions."""
    array = np.linspace(0.0, 1.0, elements, dtype=np.float64)
    return array.tolist(), array


def functions_for(
    python_values: list[float],
    numpy_values: NDArray[np.float64],
) -> dict[str, Callable[[], Result]]:
    return {
        "python_loop": lambda: python_loop(python_values),
        "numpy_vectorized": lambda: numpy_vectorized(numpy_values),
    }


def validate_results(
    python_values: list[float],
    numpy_values: NDArray[np.float64],
) -> None:
    expected = numpy_vectorized(numpy_values)
    actual = np.asarray(python_loop(python_values), dtype=np.float64)
    if not np.allclose(actual, expected, rtol=1e-12, atol=1e-12):
        raise AssertionError("Python and NumPy implementations produced different results")


def benchmark_methods(
    elements: int,
    repeats: int,
    warmups: int,
    rng: random.Random,
) -> list[Measurement]:
    python_values, numpy_values = make_inputs(elements)
    validate_results(python_values, numpy_values)
    functions = functions_for(python_values, numpy_values)
    for function in functions.values():
        for _ in range(warmups):
            function()

    measurements: list[Measurement] = []
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        for repeat in range(1, repeats + 1):
            scheduled = list(METHODS)
            rng.shuffle(scheduled)
            for run_order, method in enumerate(scheduled, start=1):
                start = time.perf_counter()
                result = functions[method]()
                elapsed = time.perf_counter() - start
                if len(result) != elements:
                    raise AssertionError("Unexpected result length")
                measurements.append(
                    Measurement(method, elements, repeat, run_order, elapsed)
                )
    finally:
        if gc_was_enabled:
            gc.enable()
    return measurements


def measure_peak_memory(elements: int) -> dict[str, int]:
    """Measure peak traced allocations of each kernel separately from timing."""
    python_values, numpy_values = make_inputs(elements)
    functions = functions_for(python_values, numpy_values)
    peaks: dict[str, int] = {}
    for method in METHODS:
        gc.collect()
        tracemalloc.start()
        try:
            baseline, _ = tracemalloc.get_traced_memory()
            result = functions[method]()
            _, peak = tracemalloc.get_traced_memory()
            peaks[method] = max(0, peak - baseline)
            if len(result) != elements:
                raise AssertionError("Unexpected result length")
        finally:
            tracemalloc.stop()
    return peaks


def summarize(
    measurements: Sequence[Measurement],
    peak_memory: Mapping[str, int],
) -> list[dict[str, Scalar]]:
    python_median = statistics.median(
        item.seconds for item in measurements if item.method == "python_loop"
    )
    rows: list[dict[str, Scalar]] = []
    for method in METHODS:
        selected = [item for item in measurements if item.method == method]
        if not selected:
            continue
        values = [item.seconds for item in selected]
        median = statistics.median(values)
        rows.append(
            {
                "method": method,
                "elements": selected[0].elements,
                "runs": len(values),
                "mean_seconds": statistics.fmean(values),
                "median_seconds": median,
                "stdev_seconds": statistics.stdev(values) if len(values) > 1 else 0.0,
                "min_seconds": min(values),
                "max_seconds": max(values),
                "throughput_melements_s": selected[0].elements / median / 1_000_000,
                "speedup_vs_python": python_median / median,
                "peak_traced_bytes": peak_memory[method],
            }
        )
    return rows


def write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def plot_summary(summary: Sequence[Mapping[str, Scalar]], path: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(path.parent / ".matplotlib-cache"))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = [str(row["method"]).replace("_", "\n") for row in summary]
    path.parent.mkdir(parents=True, exist_ok=True)
    figure, axes = plt.subplots(1, 3, figsize=(13, 4.3))
    axes[0].bar(labels, [float(row["median_seconds"]) * 1000 for row in summary])
    axes[0].set(title="Execution time", ylabel="Median time (ms)")
    axes[1].bar(
        labels,
        [float(row["speedup_vs_python"]) for row in summary],
        color="tab:orange",
    )
    axes[1].axhline(1.0, color="black", linewidth=1)
    axes[1].set(title="Speedup", ylabel="Speedup vs Python loop")
    axes[2].bar(
        labels,
        [float(row["peak_traced_bytes"]) / 1_048_576 for row in summary],
        color="tab:green",
    )
    axes[2].set(title="Kernel allocations", ylabel="Peak traced memory (MiB)")
    for axis in axes:
        axis.grid(axis="y", alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elements", type=int, default=1_000_000)
    parser.add_argument("--repeats", type=int, default=11)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260718)
    parser.add_argument(
        "--quick", action="store_true", help="Use 10,000 elements and three repeats"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path(__file__).parent / "results"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    elements = 10_000 if args.quick else args.elements
    repeats = 3 if args.quick else args.repeats
    if elements <= 0 or repeats <= 0 or args.warmups < 0:
        raise SystemExit("elements and repeats must be positive; warmups cannot be negative")
    measurements = benchmark_methods(
        elements, repeats, args.warmups, random.Random(args.seed)
    )
    peak_memory = measure_peak_memory(elements)
    summary = summarize(measurements, peak_memory)
    write_csv(args.output_dir / "raw.csv", [asdict(item) for item in measurements])
    write_csv(args.output_dir / "summary.csv", summary)
    metadata = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "numpy": np.__version__,
        "platform": platform.platform(),
        "elements": elements,
        "dtype": "float64",
        "expression": "y = x*x + 3*x",
        "repeats": repeats,
        "warmups": args.warmups,
        "seed": args.seed,
        "timer": "time.perf_counter",
        "input_creation_included": False,
        "memory_measurement": "tracemalloc peak above baseline; measured separately",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    plot_summary(summary, Path(__file__).parent / "figures" / "vectorization.png")
    print(
        f"{'method':>18}  {'median (ms)':>12}  {'speedup':>9}  {'peak traced (MiB)':>18}"
    )
    for row in summary:
        print(
            f"{row['method']:>18}  {float(row['median_seconds']) * 1000:>12.3f}  "
            f"{float(row['speedup_vs_python']):>8.2f}x  "
            f"{float(row['peak_traced_bytes']) / 1_048_576:>18.2f}"
        )


if __name__ == "__main__":
    main()
