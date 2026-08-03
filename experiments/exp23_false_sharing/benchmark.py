"""Measure adjacent versus cache-line-separated shared-memory writes."""

from __future__ import annotations
import argparse
import csv
import json
import multiprocessing as mp
import platform
import statistics
import time
from pathlib import Path


def writer(values, index, iterations):
    for i in range(iterations):
        values[index] = i


def measure(condition, workers, iterations, repeat):
    stride = 1 if condition == "adjacent" else 16
    values = mp.RawArray("q", workers * stride)
    ps = [
        mp.Process(target=writer, args=(values, i * stride, iterations))
        for i in range(workers)
    ]
    start = time.perf_counter_ns()
    for p in ps:
        p.start()
    for p in ps:
        p.join()
    if any(p.exitcode for p in ps):
        raise RuntimeError("worker failed")
    return {
        "condition": condition,
        "repeat": repeat,
        "seconds": (time.perf_counter_ns() - start) / 1e9,
        "workers": workers,
        "iterations": iterations,
        "stride_bytes": stride * 8,
        "checksum": sum(values[i * stride] for i in range(workers)),
    }


def run(workers, iterations, repeats):
    return [
        measure(c, workers, iterations, r)
        for r in range(1, repeats + 1)
        for c in ("adjacent", "separated")
    ]


def main():
    mp.freeze_support()
    p = argparse.ArgumentParser()
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--iterations", type=int, default=1000000)
    p.add_argument("--repeats", type=int, default=7)
    p.add_argument("--quick", action="store_true")
    p.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "results")
    a = p.parse_args()
    it = 10000 if a.quick else a.iterations
    reps = 3 if a.quick else a.repeats
    rows = run(a.workers, it, reps)
    base = statistics.median(x["seconds"] for x in rows if x["condition"] == "adjacent")
    summary = [
        {
            "condition": c,
            "median_seconds": (
                m := statistics.median(
                    x["seconds"] for x in rows if x["condition"] == c
                )
            ),
            "speedup_vs_adjacent": base / m,
            "stride_bytes": next(
                x["stride_bytes"] for x in rows if x["condition"] == c
            ),
        }
        for c in ("adjacent", "separated")
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
                "hardware_counters": "run equivalent worker command under Linux perf for cache events",
                "workers": a.workers,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    ax.bar([x["condition"] for x in summary], [x["median_seconds"] for x in summary])
    ax.set(ylabel="Median seconds", title="False sharing")
    fig.tight_layout()
    (Path(__file__).parent / "figures").mkdir(exist_ok=True)
    fig.savefig(Path(__file__).parent / "figures/false_sharing.png", dpi=160)
    plt.close(fig)
    print(summary)


if __name__ == "__main__":
    main()
