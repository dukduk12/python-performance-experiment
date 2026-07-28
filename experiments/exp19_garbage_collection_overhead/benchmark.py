"""Measure cyclic-garbage-collection overhead during object-heavy work."""

from __future__ import annotations
import argparse
import csv
import gc
import json
import platform
import statistics
import time
import tracemalloc
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Measurement:
    condition: str
    repeat: int
    seconds: float
    peak_bytes: int
    collections: int
    checksum: int


def workload(objects: int) -> int:
    keep = []
    checksum = 0
    for i in range(objects):
        node: list[object] = [i]
        node.append(node)
        if i % 64 == 0:
            keep.append(node)
            checksum += i
    return checksum


def measure(condition: str, objects: int, repeat: int) -> Measurement:
    gc.collect()
    before = sum(g["collections"] for g in gc.get_stats())
    was = gc.isenabled()
    if condition == "disabled":
        gc.disable()
    else:
        gc.enable()
    tracemalloc.start()
    start = time.perf_counter_ns()
    checksum = workload(objects)
    seconds = (time.perf_counter_ns() - start) / 1e9
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    after = sum(g["collections"] for g in gc.get_stats())
    if was:
        gc.enable()
    else:
        gc.disable()
    gc.collect()
    return Measurement(condition, repeat, seconds, peak, after - before, checksum)


def run(objects: int, repeats: int, warmups: int) -> list[Measurement]:
    for condition in ("enabled", "disabled"):
        for _ in range(warmups):
            measure(condition, min(objects, 2000), 0)
    return [
        measure(c, objects, r)
        for r in range(1, repeats + 1)
        for c in ("enabled", "disabled")
    ]


def summarize(rows):
    base = statistics.median(x.seconds for x in rows if x.condition == "enabled")
    return [
        {
            "condition": c,
            "runs": len(s),
            "median_seconds": statistics.median(x.seconds for x in s),
            "median_peak_bytes": statistics.median(x.peak_bytes for x in s),
            "median_collections": statistics.median(x.collections for x in s),
            "speedup_vs_enabled": base / statistics.median(x.seconds for x in s),
        }
        for c in ("enabled", "disabled")
        if (s := [x for x in rows if x.condition == c])
    ]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--objects", type=int, default=200000)
    p.add_argument("--repeats", type=int, default=9)
    p.add_argument("--warmups", type=int, default=1)
    p.add_argument("--quick", action="store_true")
    p.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "results")
    a = p.parse_args()
    n = 10000 if a.quick else a.objects
    reps = 3 if a.quick else a.repeats
    if n <= 0 or reps <= 0 or a.warmups < 0:
        raise SystemExit("invalid benchmark parameters")
    rows = run(n, reps, a.warmups)
    summary = summarize(rows)
    a.output_dir.mkdir(parents=True, exist_ok=True)
    for name, data in (
        ("raw.csv", [asdict(x) for x in rows]),
        ("summary.csv", summary),
    ):
        with (a.output_dir / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(data[0]))
            w.writeheader()
            w.writerows(data)
    (a.output_dir / "metadata.json").write_text(
        json.dumps(
            {
                "platform": platform.platform(),
                "objects": n,
                "repeats": reps,
                "timer": "perf_counter_ns",
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
    ax.set(ylabel="Median seconds", title="GC overhead")
    fig.tight_layout()
    (Path(__file__).parent / "figures").mkdir(exist_ok=True)
    fig.savefig(Path(__file__).parent / "figures/gc_overhead.png", dpi=160)
    plt.close(fig)
    print(summary)


if __name__ == "__main__":
    main()
