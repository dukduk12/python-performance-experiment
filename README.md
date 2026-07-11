# Python Performance Experiment

Small, reproducible experiments for understanding Python performance.

| Experiment                                                  | Topic                                                       | Status   |
| ----------------------------------------------------------- | ----------------------------------------------------------- | -------- |
| [Experiment 01](experiments/exp01_list_traversal/README.md) | Row-major vs. column-major traversal of nested Python lists | Complete |
| Experiment 02                                               | NumPy C-order vs. F-order memory layout                     | Planned  |

```bash
uv sync --dev
uv run python experiments/exp01_list_traversal/benchmark.py
```
