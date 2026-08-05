"""Measure how run count and fixed/randomized order affect benchmark stability."""

from __future__ import annotations
import argparse
import csv
import json
import platform
import random
import statistics
import time
from pathlib import Path


def kernel(kind, n):
    x = 0
    step = 1 if kind == "fast" else 2
    for i in range(n * step):
        x = (x + i) % 1000003
    return x


def collect(ordering, repeats, n, rng):
    rows = []
    for r in range(1, repeats + 1):
        order = ["fast", "slow"]
        if ordering == "randomized":
            rng.shuffle(order)
        for pos, c in enumerate(order, 1):
            s = time.perf_counter_ns()
            checksum = kernel(c, n)
            seconds = (time.perf_counter_ns() - s) / 1e9
            rows.append(
                {
                    "ordering": ordering,
                    "condition": c,
                    "repeat": r,
                    "run_order": pos,
                    "seconds": seconds,
                    "checksum": checksum,
                }
            )
    return rows


def summarize(rows, counts):
    out = []
    for ordering in sorted({str(row["ordering"]) for row in rows}):
        for c in sorted({str(row["condition"]) for row in rows}):
            allv = [
                x["seconds"]
                for x in rows
                if x["ordering"] == ordering and x["condition"] == c
            ]
            for count in counts:
                v = allv[:count]
                mean = statistics.mean(v)
                sd = statistics.stdev(v) if len(v) > 1 else 0
                out.append(
                    {
                        "ordering": ordering,
                        "condition": c,
                        "sample_count": count,
                        "mean_seconds": mean,
                        "median_seconds": statistics.median(v),
                        "stdev_seconds": sd,
                        "cv_percent": 100 * sd / mean if mean else 0,
                        "ci95_half_width": 1.96 * sd / (len(v) ** 0.5),
                    }
                )
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--iterations", type=int, default=100000)
    p.add_argument("--repeats", type=int, default=30)
    p.add_argument("--seed", type=int, default=20260728)
    p.add_argument("--quick", action="store_true")
    p.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "results")
    a = p.parse_args()
    n = 5000 if a.quick else a.iterations
    reps = 5 if a.quick else a.repeats
    counts = sorted({min(reps, x) for x in (3, 5, 10, 20, 30)})
    rows = collect("fixed", reps, n, random.Random(a.seed)) + collect(
        "randomized", reps, n, random.Random(a.seed)
    )
    summary = summarize(rows, counts)
    a.output_dir.mkdir(parents=True, exist_ok=True)
    for name, data in (("raw.csv", rows), ("summary.csv", summary)):
        with (a.output_dir / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(data[0]))
            w.writeheader()
            w.writerows(data)
    (a.output_dir / "metadata.json").write_text(
        json.dumps(
            {
                "platform": platform.platform(),
                "iterations": n,
                "repeats": reps,
                "seed": a.seed,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    for o in ("fixed", "randomized"):
        s = [x for x in summary if x["ordering"] == o and x["condition"] == "fast"]
        ax.plot(
            [x["sample_count"] for x in s],
            [x["cv_percent"] for x in s],
            marker="o",
            label=o,
        )
    ax.set(xlabel="Sample count", ylabel="CV (%)", title="Benchmark stability")
    ax.legend()
    fig.tight_layout()
    (Path(__file__).parent / "figures").mkdir(exist_ok=True)
    fig.savefig(Path(__file__).parent / "figures/stability.png", dpi=160)
    plt.close(fig)
    print(summary[-4:])


if __name__ == "__main__":
    main()
