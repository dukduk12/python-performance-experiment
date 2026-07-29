"""Compare deep memory cost of Python integers and a NumPy integer array."""

from __future__ import annotations
import argparse
import csv
import json
import platform
import sys
from pathlib import Path
import numpy as np


def measure(size: int) -> list[dict[str, object]]:
    values = list(range(size))
    array = np.arange(size, dtype=np.int64)
    list_bytes = sys.getsizeof(values) + sum(sys.getsizeof(x) for x in values)
    array_bytes = sys.getsizeof(array)
    return [
        {
            "condition": "list[int]",
            "elements": size,
            "container_bytes": sys.getsizeof(values),
            "payload_bytes": list_bytes - sys.getsizeof(values),
            "total_bytes": list_bytes,
            "bytes_per_element": list_bytes / size,
        },
        {
            "condition": "ndarray[int64]",
            "elements": size,
            "container_bytes": sys.getsizeof(array) - array.nbytes,
            "payload_bytes": array.nbytes,
            "total_bytes": array_bytes,
            "bytes_per_element": array_bytes / size,
        },
    ]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sizes", type=int, nargs="+", default=[1000, 100000, 1000000])
    p.add_argument("--quick", action="store_true")
    p.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "results")
    a = p.parse_args()
    sizes = [10, 1000] if a.quick else a.sizes
    if any(n <= 0 for n in sizes):
        raise SystemExit("sizes must be positive")
    rows = [r for n in sizes for r in measure(n)]
    a.output_dir.mkdir(parents=True, exist_ok=True)
    with (a.output_dir / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (a.output_dir / "metadata.json").write_text(
        json.dumps(
            {
                "python": sys.version,
                "numpy": np.__version__,
                "platform": platform.platform(),
                "accounting": "shallow container plus element sizes",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    [
        ax.plot(
            sizes,
            [float(r["bytes_per_element"]) for r in rows if r["condition"] == c],
            marker="o",
            label=c,
        )
        for c in ("list[int]", "ndarray[int64]")
    ]
    ax.set(
        xscale="log",
        xlabel="Elements",
        ylabel="Bytes per element",
        title="CPython object overhead",
    )
    ax.legend()
    fig.tight_layout()
    (Path(__file__).parent / "figures").mkdir(exist_ok=True)
    fig.savefig(Path(__file__).parent / "figures/object_overhead.png", dpi=160)
    plt.close(fig)
    print(rows)


if __name__ == "__main__":
    main()
