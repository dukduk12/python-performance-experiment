# Python Performance Experiment

Small, reproducible experiments for understanding Python performance.

| Experiment                                                       | Topic                        | Summary                                                                         |
| ---------------------------------------------------------------- | ---------------------------- | ------------------------------------------------------------------------------- |
| [Experiment 01](experiments/exp01_list_traversal/README.md)      | Python Nested List Traversal | Compares row-first and column-first traversal of nested Python lists.           |
| [Experiment 02](experiments/exp02_numpy_memory_layout/README.md) | NumPy Memory Layout          | Measures how C/F memory order interacts with row-first and column-first access. |
| [Experiment 03](experiments/exp03_python_vs_numba/README.md)     | Pure Python vs Numba         | Shows how interpreter overhead masks traversal-order and memory-locality costs. |
| [Experiment 04](experiments/exp04_array_size_scaling/README.md)  | Array Size Scaling           | Measures how array growth changes traversal throughput and access-order cost.   |
| [Experiment 05](experiments/exp05_data_type_element_size/README.md) | Data Type and Element Size | Measures how NumPy element width changes memory use and contiguous-copy throughput. |
| [Experiment 06](experiments/exp06_contiguous_vs_non_contiguous/README.md) | Contiguous vs Non-Contiguous Arrays | Compares copy cost, strides, and contiguity flags for contiguous arrays and sliced/transposed views. |
