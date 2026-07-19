<div align="center">

# Python Performance Laboratory

### An Experimental Study of Interpreter Overhead, Memory Layout, and Data Locality

<p>
  <strong>A living, reproducible research repository</strong><br>
  Small controlled experiments that connect Python code to runtime and hardware behavior.
</p>

<p>
  <code>CPython</code> · <code>NumPy</code> · <code>Numba</code> · <code>Linux perf</code>
</p>

</div>

---

<table>
  <tr>
    <td><strong>Study type</strong></td>
    <td>Controlled performance experiments</td>
    <td><strong>Implemented</strong></td>
    <td>10 experiments</td>
  </tr>
  <tr>
    <td><strong>Primary metrics</strong></td>
    <td>Time, throughput, memory, cache events</td>
    <td><strong>Languages</strong></td>
    <td>Python and compiled NumPy/Numba kernels</td>
  </tr>
  <tr>
    <td><strong>Method</strong></td>
    <td>Warmups, repeated trials, medians</td>
    <td><strong>Repository type</strong></td>
    <td>Living experiment collection</td>
  </tr>
</table>

## Abstract

Python performance is not determined by syntax alone. It emerges from several interacting layers: CPython interpreter overhead, object representation, array layout, compiled numerical kernels, CPU caches, and memory bandwidth.

This repository investigates those layers through small, independently reproducible experiments. The first ten studies move from Python nested-list traversal to NumPy memory layout, Numba compilation, working-set scaling, element width, non-contiguous views, vectorization, hardware cache-counter measurement, CPU-bound threading under the Global Interpreter Lock, and multiprocessing across independent interpreters.

The reference results show three recurring patterns:

1. Access order matters, but Python interpreter work can hide much of its cost.
2. Compiled and vectorized execution exposes memory-layout effects more clearly.
3. Moving contiguous bytes efficiently is often more important than the nominal numeric type.

These findings are observations from documented benchmark environments, not universal constants. Each experiment records its assumptions and limitations.

## 1. Python: A Short Performance Primer

Python is a high-level, dynamically typed language designed for clarity and developer productivity. In the standard CPython implementation, a loop normally executes interpreter bytecode and repeatedly performs dynamic type checks, object access, and reference-count operations.

That model is flexible, but it adds work to every iteration. A Python `int` or `float` is also an object with metadata rather than only a raw numeric value. Consequently, a simple loop can spend more time managing the Python runtime than performing arithmetic.

### The GIL, Threads, and Processes

Most standard CPython builds use a **Global Interpreter Lock (GIL)**. A thread must hold this lock while it executes Python bytecode, so multiple threads in one process normally cannot run a pure-Python CPU loop on several cores at the same instant. The operating system may move those threads among cores, but their bytecode execution is still serialized by the lock.

This does not make threading useless. Threads can overlap network, file, and other waiting operations because the active thread can release the GIL while it waits. NumPy and other native extensions may also release the GIL around compiled work. For CPU-bound pure-Python code, separate processes can provide true parallel execution because every process owns a separate interpreter and GIL, although process startup, serialization, and inter-process communication introduce costs.

NumPy changes the execution model by storing homogeneous values in compact multidimensional buffers. Numba can compile selected Python functions into machine code. These tools reduce interpreter overhead, making lower-level effects such as strides, cache locality, memory bandwidth, and native parallel execution easier to observe.

<blockquote>
  <strong>Central idea:</strong> optimization begins by identifying which layer is dominant—the interpreter, data representation, memory access, allocation, or hardware.
</blockquote>

## 2. Scope and Research Questions

This study currently focuses on single-process numerical and memory-access behavior. It asks:

- Does row-first traversal outperform column-first traversal?
- How do C-order and F-order arrays interact with traversal direction?
- Does removing interpreter overhead reveal stronger locality effects?
- How does the penalty change as the working set grows?
- Does element width affect element throughput or byte throughput?
- What cost is deferred when a cheap NumPy view is non-contiguous?
- How much does vectorization improve execution time and allocation behavior?
- Do timing differences occur alongside hardware cache misses?
- Do additional Python threads accelerate a CPU-bound pure-Python workload?
- When does multiprocessing accelerate a CPU-bound pure-Python workload?

Task-size overhead, garbage collection, object overhead, alternative Python runtimes, and asynchronous I/O remain planned studies in [`table.md`](table.md).

## 3. Experimental Method

Each experiment lives in an independent directory and contains its own research question, hypothesis, benchmark, results, discussion, limitations, and reproduction instructions.

The shared methodology is:

```text
Define one comparison
        ↓
Create equivalent workloads
        ↓
Validate correctness
        ↓
Warm up the runtime or compiler
        ↓
Randomize condition order
        ↓
Repeat measurements
        ↓
Report medians and variability
        ↓
Interpret within documented limits
```

Input construction is normally excluded from timed kernels unless allocation is the subject of the experiment. Median time is the primary statistic because benchmark distributions often contain scheduling and frequency-related outliers. Exact protocols are documented per experiment.

## 4. Principal Findings

<table>
  <thead>
    <tr>
      <th>Finding</th>
      <th>Reference observation</th>
      <th>Interpretation</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>Traversal order affects nested lists</strong></td>
      <td>Row-first was 1.76–2.71× faster in Experiment 01.</td>
      <td>Access pattern matters, although Python indexing costs are not identical.</td>
    </tr>
    <tr>
      <td><strong>Interpreter overhead masks locality</strong></td>
      <td>Python showed at most a 1.07× traversal penalty, while Numba exposed 3.19–7.67× in Experiment 03.</td>
      <td>Once interpreter work is removed, memory access becomes a larger share of runtime.</td>
    </tr>
    <tr>
      <td><strong>Large working sets amplify poor access order</strong></td>
      <td>The column-first penalty grew from 2.33× at 0.03 MiB to 34.78× at 128 MiB in Experiment 04.</td>
      <td>Contiguous traversal retained much higher throughput as the array grew.</td>
    </tr>
    <tr>
      <td><strong>Byte movement dominates contiguous copying</strong></td>
      <td>Different dtypes reached roughly 26.59–27.52 GiB/s in Experiment 05.</td>
      <td>Element throughput changed with width, while effective byte throughput stayed similar.</td>
    </tr>
    <tr>
      <td><strong>Views can defer substantial cost</strong></td>
      <td>A sliced view was 2.47× slower and a transposed source 12.14× slower than the contiguous source in Experiment 06.</td>
      <td>Creating a view is cheap, but later operations still pay for unfavorable strides.</td>
    </tr>
    <tr>
      <td><strong>Vectorization removes per-element Python work</strong></td>
      <td>NumPy was 5.35× faster and used less peak traced allocation in Experiment 07.</td>
      <td>Compiled array loops outperform repeated dynamic Python operations for this workload.</td>
    </tr>
    <tr>
      <td><strong>CPU-bound Python threads did not scale</strong></td>
      <td>Two and four threads achieved 0.97× and 0.98× sequential speed in Experiment 09.</td>
      <td>The GIL kept this pure-Python workload near one-core utilization while thread management added overhead.</td>
    </tr>
    <tr>
      <td><strong>Separate processes enabled CPU parallelism</strong></td>
      <td>Two and four processes achieved 1.66× and 2.37× speedup in Experiment 10.</td>
      <td>Independent interpreters bypassed the single-process GIL, while overhead and shared resources kept scaling sublinear.</td>
    </tr>
  </tbody>
</table>

<sub>
Reference values are machine- and workload-specific. Timing alone does not prove a cache mechanism; Experiment 08 is designed to add hardware-counter evidence.
</sub>

## 5. Experiment Index

| No. | Experiment | Question | Status |
| ---: | --- | --- | :---: |
| 01 | [Python Nested List Traversal](experiments/exp01_list_traversal/README.md) | Is row-first traversal faster for nested Python lists? | Complete |
| 02 | [NumPy Memory Layout](experiments/exp02_numpy_memory_layout/README.md) | Does matching traversal direction to C/F storage order help? | Complete |
| 03 | [Pure Python vs Numba](experiments/exp03_python_vs_numba/README.md) | Does interpreter overhead hide memory-locality costs? | Complete |
| 04 | [Array Size Scaling](experiments/exp04_array_size_scaling/README.md) | Does poor traversal become more expensive as arrays grow? | Complete |
| 05 | [Data Type and Element Size](experiments/exp05_data_type_element_size/README.md) | How does element width affect memory use and throughput? | Complete |
| 06 | [Contiguous vs Non-Contiguous Arrays](experiments/exp06_contiguous_vs_non_contiguous/README.md) | What cost do slices and transposed views impose later? | Complete |
| 07 | [Vectorization vs Python Loops](experiments/exp07_vectorization_vs_python_loops/README.md) | How much interpreter overhead does vectorization remove? | Complete |
| 08 | [Cache Miss Measurement](experiments/exp08_cache_miss_measurement/README.md) | Do runtime differences coincide with cache miss behavior? | Awaiting Linux measurement |
| 09 | [Sequential vs Threading](experiments/exp09_sequential_vs_threading/README.md) | Why do more threads not accelerate CPU-bound Python work? | Complete |
| 10 | [Sequential vs Multiprocessing](experiments/exp10_sequential_vs_multiprocessing/README.md) | When do processes accelerate CPU-bound Python work? | Complete |

The complete research roadmap is maintained in [`table.md`](table.md).

## 6. Reproducing the Study

### Requirements

- Python 3.13 or 3.14
- [`uv`](https://docs.astral.sh/uv/) for environment and dependency management
- Linux and `perf` only for Experiment 08 hardware counters

### Setup

```bash
git clone <repository-url>
cd Python_Exp
uv sync
```

### Run an experiment

```bash
uv run python experiments/exp07_vectorization_vs_python_loops/benchmark.py
```

Most benchmarks also provide a smaller smoke-test configuration:

```bash
uv run python experiments/exp07_vectorization_vs_python_loops/benchmark.py --quick
```

### Verify the repository

```bash
uv run pytest
uv run ruff check .
uv run mypy experiments
```

Generated measurements and figures belong to their experiment directories. Consult the experiment README before comparing values across machines.

## 7. Interpretation and Limitations

The experiments favor understandable controlled comparisons over comprehensive hardware characterization. Reference measurements were collected on one environment per experiment. CPU frequency, scheduling, thermal state, cache history, page placement, compiler decisions, library versions, and background activity can change the observed ratios.

Several studies infer memory-locality effects from timing and stride metadata. Such evidence is consistent with a cache explanation but does not establish cache misses as the sole cause. Experiment 08 explicitly measures generic cache events, although those events also vary by CPU and kernel mapping.

The appropriate conclusion is therefore not that one fixed speedup applies everywhere. It is that data representation, execution layer, working-set size, and access order must be measured together.

## 8. Repository Structure

```text
Python_Exp/
├── experiments/
│   ├── exp01_list_traversal/
│   ├── ...
│   └── exp10_sequential_vs_multiprocessing/
├── tests/
├── table.md
├── prompt.md
└── pyproject.toml
```

## 9. Current Conclusion

The experiments completed so far support a layered view of Python performance:

<div align="center">

**Python runtime and GIL → data representation → memory access pattern → hardware behavior**

</div>

Optimizing only the visible loop can miss the actual bottleneck. Pure Python code may be interpreter- or GIL-bound; compiled code may become locality-bound; contiguous bulk operations may become bandwidth-bound. Threads help when work waits or releases the GIL, but they did not parallelize the pure-Python CPU loop measured here. Separate processes did parallelize the same class of CPU work, although their efficiency declined as worker count increased. Reliable performance work therefore requires controlled measurement, correctness checks, and conclusions limited to the evidence collected.

---

<div align="center">
  <sub>This repository is intentionally iterative. Results are revised as experiments, platforms, and measurement methods improve.</sub>
</div>
