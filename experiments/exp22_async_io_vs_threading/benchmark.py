"""Compare sequential, threaded, and asyncio simulated I/O."""

from __future__ import annotations
import argparse
import asyncio
import csv
import json
import platform
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def sequential(tasks, delay):
    [time.sleep(delay) for _ in range(tasks)]


def threaded(tasks, delay, workers):
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(time.sleep, [delay] * tasks))


async def async_work(tasks, delay):
    await asyncio.gather(*(asyncio.sleep(delay) for _ in range(tasks)))


def once(condition, tasks, delay, workers):
    s = time.perf_counter_ns()
    if condition == "sequential":
        sequential(tasks, delay)
    elif condition == "threading":
        threaded(tasks, delay, workers)
    else:
        asyncio.run(async_work(tasks, delay))
    return (time.perf_counter_ns() - s) / 1e9


def run(tasks, delay, workers, repeats):
    return [
        {
            "condition": c,
            "repeat": r,
            "seconds": once(c, tasks, delay, workers),
            "tasks_per_second": tasks / once(c, 0, 0, workers) if False else 0,
        }
        for r in range(1, repeats + 1)
        for c in ("sequential", "threading", "asyncio")
    ]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tasks", type=int, default=100)
    p.add_argument("--delay", type=float, default=0.02)
    p.add_argument("--workers", type=int, default=20)
    p.add_argument("--repeats", type=int, default=7)
    p.add_argument("--quick", action="store_true")
    p.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "results")
    a = p.parse_args()
    tasks = 12 if a.quick else a.tasks
    delay = 0.002 if a.quick else a.delay
    reps = 3 if a.quick else a.repeats
    rows = run(tasks, delay, a.workers, reps)
    for x in rows:
        x["tasks_per_second"] = tasks / x["seconds"]
    base = statistics.median(
        x["seconds"] for x in rows if x["condition"] == "sequential"
    )
    summary = [
        {
            "condition": c,
            "median_seconds": (
                m := statistics.median(
                    x["seconds"] for x in rows if x["condition"] == c
                )
            ),
            "speedup": base / m,
            "throughput": tasks / m,
        }
        for c in ("sequential", "threading", "asyncio")
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
                "tasks": tasks,
                "delay": delay,
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
    ax.set(ylabel="Median seconds", title="I/O concurrency")
    fig.tight_layout()
    (Path(__file__).parent / "figures").mkdir(exist_ok=True)
    fig.savefig(Path(__file__).parent / "figures/io_concurrency.png", dpi=160)
    plt.close(fig)
    print(summary)


if __name__ == "__main__":
    main()
