# Python Performance Experiment

Small, reproducible experiments for understanding Python performance.

| Experiment                                                       | Topic                        | Summary                                                                         |
| ---------------------------------------------------------------- | ---------------------------- | ------------------------------------------------------------------------------- |
| [Experiment 01](experiments/exp01_list_traversal/README.md)      | Python Nested List Traversal | Compares row-first and column-first traversal of nested Python lists.           |
| [Experiment 02](experiments/exp02_numpy_memory_layout/README.md) | NumPy Memory Layout          | Measures how C/F memory order interacts with row-first and column-first access. |
| [Experiment 03](experiments/exp03_python_vs_numba/README.md)     | Pure Python vs Numba         | Shows how interpreter overhead masks traversal-order and memory-locality costs. |
| [Experiment 04](experiments/exp04_array_size_scaling/README.md)  | Array Size Scaling           | Measures how array growth changes traversal throughput and access-order cost.   |
