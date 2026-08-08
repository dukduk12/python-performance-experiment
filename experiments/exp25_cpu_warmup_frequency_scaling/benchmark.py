"""Record cold-to-warm timing sequence and optional CPU frequency observations."""

from __future__ import annotations
import argparse
import csv
import json
import platform
import statistics
import time
from pathlib import Path
import psutil


def kernel(n):
    x = 1
    for i in range(1, n):
        x = (x * 33 + i) % 1000000007
    return x


def run(iterations, runs):
    rows = []
    for i in range(1, runs + 1):
        freq = psutil.cpu_freq()
        start = time.perf_counter_ns()
        checksum = kernel(iterations)
        seconds = (time.perf_counter_ns() - start) / 1e9
        rows.append(
            {
                "run": i,
                "phase": "cold" if i == 1 else "warm",
                "seconds": seconds,
                "cpu_mhz": freq.current if freq else "",
                "checksum": checksum,
            }
        )
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--iterations", type=int, default=1000000)
    p.add_argument("--runs", type=int, default=30)
    p.add_argument("--quick", action="store_true")
    p.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "results")
    a = p.parse_args()
    n = 10000 if a.quick else a.iterations
    runs = 5 if a.quick else a.runs
    rows = run(n, runs)
    warm = [x["seconds"] for x in rows[1:]]
    summary = [
        {
            "first_seconds": rows[0]["seconds"],
            "warm_median_seconds": statistics.median(warm),
            "first_vs_warm_ratio": rows[0]["seconds"] / statistics.median(warm),
            "runs": runs,
        }
    ]
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
                "runs": runs,
                "frequency_source": "psutil.cpu_freq sampled before each run",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    ax.plot([x["run"] for x in rows], [x["seconds"] for x in rows], marker="o")
    ax.axhline(summary[0]["warm_median_seconds"], ls="--", label="warm median")
    ax.set(xlabel="Run", ylabel="Seconds", title="Cold and warm runs")
    ax.legend()
    fig.tight_layout()
    (Path(__file__).parent / "figures").mkdir(exist_ok=True)
    fig.savefig(Path(__file__).parent / "figures/warmup.png", dpi=160)
    plt.close(fig)
    print(summary)


if __name__ == "__main__":
    main()
