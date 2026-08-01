"""Run the same loop in available CPython and PyPy interpreters."""

from __future__ import annotations
import argparse
import csv
import json
import platform
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

CODE = "import json,sys,time\nn=int(sys.argv[1]);r=int(sys.argv[2]);out=[]\nfor _ in range(r):\n s=time.perf_counter_ns();x=0\n for i in range(n):x=(x+i*i)%1000000007\n out.append((time.perf_counter_ns()-s)/1e9)\nprint(json.dumps({'implementation':sys.implementation.name,'times':out,'checksum':x}))"


def available_interpreters():
    found = {"cpython": sys.executable}
    pypy = shutil.which("pypy3") or shutil.which("pypy")
    if pypy:
        found["pypy"] = pypy
    return found


def run(interpreters, iterations, repeats):
    rows = []
    for label, exe in interpreters.items():
        data = json.loads(
            subprocess.check_output(
                [exe, "-c", CODE, str(iterations), str(repeats)], text=True
            )
        )
        for i, t in enumerate(data["times"], 1):
            rows.append(
                {
                    "interpreter": label,
                    "repeat": i,
                    "seconds": t,
                    "checksum": data["checksum"],
                }
            )
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--iterations", type=int, default=2000000)
    p.add_argument("--repeats", type=int, default=7)
    p.add_argument("--quick", action="store_true")
    p.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "results")
    a = p.parse_args()
    n = 20000 if a.quick else a.iterations
    r = 3 if a.quick else a.repeats
    rows = run(available_interpreters(), n, r)
    summary = [
        {
            "interpreter": c,
            "runs": len(s),
            "first_seconds": s[0]["seconds"],
            "median_seconds": statistics.median(x["seconds"] for x in s),
            "warmup_ratio": s[0]["seconds"] / min(x["seconds"] for x in s),
        }
        for c in sorted({x["interpreter"] for x in rows})
        if (s := [x for x in rows if x["interpreter"] == c])
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
                "interpreters": available_interpreters(),
                "pypy_available": "pypy" in available_interpreters(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(summary)


if __name__ == "__main__":
    main()
