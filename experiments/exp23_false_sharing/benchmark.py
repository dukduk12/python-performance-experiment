"""Measure adjacent versus cache-line-separated shared-memory writes."""

from __future__ import annotations

import argparse
import csv
import json
import multiprocessing as mp
import platform
import random
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

CONDITIONS = ("adjacent", "separated")


@dataclass(frozen=True)
class Measurement:
    condition: str
    repeat: int
    run_order: int
    seconds: float
    workers: int
    iterations: int
    stride_bytes: int
    checksum: int


def writer(values: mp.RawArray, index: int, iterations: int) -> None:
    for i in range(iterations):
        values[index] = i


def stride_elements_for(condition: str) -> int:
    if condition == "adjacent":
        return 1
    if condition == "separated":
        return 16
    raise ValueError(f"unknown condition: {condition}")


def measure(condition: str, workers: int, iterations: int, repeat: int, run_order: int) -> Measurement:
    stride = stride_elements_for(condition)
    values = mp.RawArray("q", workers * stride)
    processes = [
        mp.Process(target=writer, args=(values, i * stride, iterations))
        for i in range(workers)
    ]
    start = time.perf_counter_ns()
    for process in processes:
        process.start()
    for process in processes:
        process.join()
    if any(process.exitcode for process in processes):
        raise RuntimeError("worker failed")
    return Measurement(
        condition=condition,
        repeat=repeat,
        run_order=run_order,
        seconds=(time.perf_counter_ns() - start) / 1e9,
        workers=workers,
        iterations=iterations,
        stride_bytes=stride * 8,
        checksum=sum(values[i * stride] for i in range(workers)),
    )


def run(
    workers: int,
    iterations: int,
    repeats: int,
    seed: int = 20260809,
    conditions: Sequence[str] = CONDITIONS,
) -> list[Measurement]:
    rng = random.Random(seed)
    rows: list[Measurement] = []
    for repeat in range(1, repeats + 1):
        scheduled = list(conditions)
        rng.shuffle(scheduled)
        for run_order, condition in enumerate(scheduled, start=1):
            rows.append(measure(condition, workers, iterations, repeat, run_order))
    return rows


def summarize(measurements: Sequence[Measurement]) -> list[dict[str, float | int | str]]:
    adjacent = [
        item.seconds for item in measurements if item.condition == "adjacent"
    ]
    base = statistics.median(adjacent) if adjacent else None
    rows: list[dict[str, float | int | str]] = []
    for condition in CONDITIONS:
        selected = [item for item in measurements if item.condition == condition]
        if not selected:
            continue
        times = [item.seconds for item in selected]
        median_seconds = statistics.median(times)
        rows.append(
            {
                "condition": condition,
                "runs": len(selected),
                "median_seconds": median_seconds,
                "min_seconds": min(times),
                "max_seconds": max(times),
                "stdev_seconds": statistics.stdev(times) if len(times) > 1 else 0.0,
                "speedup_vs_adjacent": (
                    (base / median_seconds) if base is not None else 1.0
                ),
                "stride_bytes": selected[0].stride_bytes,
            }
        )
    return rows


def write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--iterations", type=int, default=1000000)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--seed", type=int, default=20260809)
    parser.add_argument(
        "--condition",
        choices=CONDITIONS,
        action="append",
        dest="conditions",
        help="Run only the selected condition. Repeat to run multiple conditions.",
    )
    parser.add_argument("--quick", action="store_true")
    parser.add_argument(
        "--output-dir", type=Path, default=Path(__file__).parent / "results"
    )
    return parser.parse_args()


def main() -> None:
    mp.freeze_support()
    args = parse_args()
    iterations = 10000 if args.quick else args.iterations
    repeats = 3 if args.quick else args.repeats
    if args.workers <= 0 or iterations <= 0 or repeats <= 0:
        raise SystemExit("workers, iterations, and repeats must be positive")
    selected_conditions = tuple(args.conditions) if args.conditions else CONDITIONS

    rows = run(
        args.workers,
        iterations,
        repeats,
        seed=args.seed,
        conditions=selected_conditions,
    )
    summary = summarize(rows)
    write_csv(args.output_dir / "raw.csv", [asdict(row) for row in rows])
    write_csv(args.output_dir / "summary.csv", summary)
    metadata = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "start_method": mp.get_start_method(),
        "workers": args.workers,
        "iterations": iterations,
        "repeats": repeats,
        "seed": args.seed,
        "conditions": list(selected_conditions),
        "adjacent_stride_bytes": stride_elements_for("adjacent") * 8,
        "separated_stride_bytes": stride_elements_for("separated") * 8,
        "hardware_counter_followup": (
            "run one condition per process under Linux perf or perf c2c for "
            "cache/coherence events"
        ),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    ax.bar([row["condition"] for row in summary], [row["median_seconds"] for row in summary])
    ax.set(ylabel="Median seconds", title="False sharing")
    fig.tight_layout()
    (Path(__file__).parent / "figures").mkdir(exist_ok=True)
    fig.savefig(Path(__file__).parent / "figures/false_sharing.png", dpi=160)
    plt.close(fig)
    print(summary)


if __name__ == "__main__":
    main()
