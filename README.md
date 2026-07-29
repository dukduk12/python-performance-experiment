<div align="center">

# Python Performance Laboratory

### From Python Objects and the GIL to CPU Caches, Memory, and Parallelism

<p>
  <strong>A living, reproducible research repository</strong><br>
  Small controlled experiments that connect Python code to runtime and hardware behavior.
</p>

<p>
  <code>CPython</code> · <code>NumPy</code> · <code>Numba</code> · <code>threadpoolctl</code> · <code>psutil</code>
</p>

</div>

---

<table>
  <tr>
    <td><strong>Study type</strong></td>
    <td>Controlled performance experiments</td>
    <td><strong>Implemented</strong></td>
    <td>25 experiments</td>
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

## What This Repository Is

Python performance is not determined by syntax alone. It emerges from several interacting layers: CPython interpreter overhead, object representation, array layout, compiled numerical kernels, CPU caches, and memory bandwidth.

This repository is a hands-on Python performance laboratory. It starts with
basic questions—such as why loop order matters—and gradually moves toward
memory layout, compiled execution, concurrency, garbage collection, runtime
implementations, false sharing, and benchmark reliability.

It is not a finished application or a collection of isolated timing tricks.
Each directory contains a small research study with a question, hypothesis,
controlled workload, executable benchmark, raw measurements, summary data,
figure, discussion, and limitations. The repository is designed to grow while
keeping every experiment independently understandable and reproducible.

The experiments are organized around five recurring ideas:

1. Python runtime overhead can dominate a small loop.
2. Data representation and memory layout affect what the hardware must do.
3. Threads, processes, and native libraries follow different parallelism rules.
4. Allocation, ownership, garbage collection, and copying exchange time for memory.
5. A performance claim is only as reliable as its measurement method.

These findings are observations from documented benchmark environments, not universal constants. Each experiment records its assumptions and limitations.

## 1. Performance Foundations

### 1.1 Python and CPython

Python is a programming language; CPython is its most widely used
implementation. CPython compiles source code to bytecode and executes that
bytecode in an interpreter. A Python loop therefore performs more than the
visible arithmetic: it dispatches bytecode, resolves dynamic types, accesses
objects, updates reference counts, and handles exceptions and iteration
protocols.

That model is flexible, but it adds work to every iteration. A Python `int` is
also a heap object with type and reference-count metadata, while a list stores
references to objects rather than unboxed numeric values. A simple numeric loop
can consequently spend more time managing Python semantics than performing its
arithmetic.

### 1.2 Contiguous Data and NumPy

NumPy uses a different representation. An `int64` array normally stores
fixed-width eight-byte values in one homogeneous buffer. Its shape and strides
describe how logical indices map to memory:

```text
address = base + row × row_stride + column × column_stride
```

A C-order two-dimensional array stores the last axis contiguously. An F-order
array stores the first axis contiguously. Slices and transposes can create
views that share the same buffer with different shape and stride metadata.
Creating a view is cheap, but a later operation may still pay for a
non-contiguous access pattern.

### 1.3 CPU Caches and Locality

CPUs do not normally fetch one scalar from main memory in isolation. Data moves
through a hierarchy of cache lines and cache levels. Sequential access tends
to reuse the bytes already fetched in a cache line and is easier for hardware
prefetchers to predict. Large-stride access can load many cache lines while
using only a small part of each one.

This is why row-first and column-first traversal can behave differently even
when both visit exactly the same values. The size of the working set matters:
an unfavorable pattern may be barely visible when data fits in cache and much
more expensive when it repeatedly reaches lower cache levels or memory.

Timing alone, however, does not prove that cache misses caused a difference.
Hardware counters, layout metadata, controlled comparisons, and repeated
measurements provide stronger evidence together.

### 1.4 Vectorization and Compilation

Vectorization moves a loop from Python bytecode into a compiled native
implementation. Numba takes another route by compiling selected Python
functions to machine code. Both approaches reduce per-element interpreter
work. Once that overhead is removed, memory bandwidth, cache locality, SIMD,
and native thread pools can become the dominant constraints.

Vectorization is not synonymous with “always faster.” Temporary arrays,
allocation, dtype conversion, non-contiguous input, or an unsuitable kernel
can reduce its benefit. The actual operation and data layout still need to be
measured.

### 1.5 The GIL, Threads, and Processes

Most standard CPython builds use a **Global Interpreter Lock (GIL)**.[^free-threaded]
A thread must hold this lock while it executes Python bytecode, so multiple
threads in one process normally cannot run a pure-Python CPU loop on several
cores at the same instant. The operating system may move those threads among
cores, but their bytecode execution is still serialized by the lock.

This does not make threading useless. Threads can overlap network, file, and other waiting operations because the active thread can release the GIL while it waits. NumPy and other native extensions may also release the GIL around compiled work. For CPU-bound pure-Python code, separate processes can provide true parallel execution because every process owns a separate interpreter and GIL, although process startup, serialization, and inter-process communication introduce costs.

NumPy changes the execution model by storing homogeneous values in compact multidimensional buffers. Numba can compile selected Python functions into machine code. These tools reduce interpreter overhead, making lower-level effects such as strides, cache locality, memory bandwidth, and native parallel execution easier to observe.

Native libraries add another layer. NumPy ufuncs may release the GIL, and BLAS
implementations may create their own worker threads. Combining a Python thread
pool with a native thread pool can create more runnable threads than the
machine can use effectively. This is called oversubscription.

[^free-threaded]: Starting with Python 3.13, CPython also provides an optional
    free-threaded build based on [PEP 703](https://peps.python.org/pep-0703/)
    that can run with the GIL disabled and allow Python threads to execute in
    parallel on multiple cores. Python 3.13 introduced this configuration as
    experimental; it is separate from the regular GIL-enabled build and is not
    the default. Some C-extension modules may also re-enable the GIL when they
    are not marked as free-threading compatible. See the official
    [free-threaded CPython guide](https://docs.python.org/3/howto/free-threading-python.html).

### 1.6 Allocation, Ownership, and Garbage Collection

Performance is also affected by object lifetime. Copying an array duplicates
its payload and gives the result independent ownership. A view usually creates
only a small metadata object, shares the original storage, and may defer costs
to later operations.

CPython primarily uses reference counting, supplemented by a cyclic garbage
collector[^gfg-gc]. Reference counting can immediately reclaim most objects but cannot
alone reclaim unreachable reference cycles. Disabling cyclic GC can remove
collection work from a measured region, while allowing cyclic garbage and
memory use to accumulate until a later explicit collection.

[^gfg-gc]: GeeksforGeeks, *Garbage Collection in Python*.
    Explains Python's garbage collection mechanism, including reference
    counting, cyclic garbage collection, the `gc` module, and common examples.
    Available at:
    https://www.geeksforgeeks.org/python/garbage-collection-python/
    (accessed July 29, 2026).

### 1.7 Basic Benchmark Terms

| Term | Meaning |
| --- | --- |
| Latency | Time required for one operation or one batch |
| Throughput | Amount of work completed per unit time |
| Speedup | Baseline time divided by comparison time |
| Scaling efficiency | Speedup divided by worker count |
| Warm-up | Unreported work used to initialize caches, JITs, pools, or libraries |
| Median | Middle sample; less sensitive to extreme outliers than the mean |
| Standard deviation | Absolute spread around the sample mean |
| Coefficient of variation | Standard deviation relative to the mean |
| Working set | Data actively touched by a workload |
| Contiguous | Elements of interest are adjacent in memory |
| View | Array metadata that shares another array's storage |
| Copy | Independently owned data produced by duplicating a payload |

<blockquote>
  <strong>Central idea:</strong> optimization begins by identifying which layer is dominant—the interpreter, data representation, memory access, allocation, or hardware.
</blockquote>

## 2. Scope and Research Questions

The repository covers six connected areas:

- interpreter and loop overhead;
- array representation, layout, and memory locality;
- threading, multiprocessing, asyncio, and native parallelism;
- allocation, ownership, object overhead, and garbage collection;
- runtime and hardware effects;
- benchmark methodology and result stability.

The complete set of research questions is:

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
- How large must CPU-bound tasks become before multiprocessing overhead is recovered?
- Why does threading help waiting tasks but not CPU-bound Python bytecode?
- How do speedup and efficiency change as process-worker count increases?
- Can independent NumPy operations run concurrently in Python threads?
- How does the native BLAS thread count affect matrix-multiplication performance?
- When do combined Python and BLAS thread pools create counterproductive oversubscription?
- How different are the creation-time and memory costs of copies and views?
- How does a cheap transpose view compare with a contiguous copy during creation and later traversal?
- What runtime and memory trade-off does cyclic garbage collection create?
- How much more memory does a Python integer list require than a NumPy array?
- How do CPython and PyPy loop performance and warm-up differ?
- How do sequential I/O, threading, and asyncio compare?
- Does separating concurrently written shared values reduce false sharing?
- How do repetition count and condition order affect benchmark stability?
- How different are a cold first run and later warm runs?

### Out of Scope

The repository does not attempt to rank every Python implementation, provide
production tuning values, or replace application profiling. It does not claim
that one measured speedup transfers unchanged to another CPU, operating system,
library build, dataset, or workload.

The experiments deliberately prefer small controlled comparisons over complete
application realism. Their purpose is to expose mechanisms and measurement
techniques that can later be applied to real programs.

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

Input construction is normally excluded from timed kernels unless allocation
is the subject of the experiment. Median time is the primary statistic because
benchmark distributions often contain scheduling and frequency-related
outliers. Exact protocols are documented per experiment.

### Measurement Rules

- Compare equivalent work and verify results with checksums or array equality.
- Use `time.perf_counter_ns()` for elapsed wall-clock measurements.
- Warm up JIT compilation, worker pools, and native libraries where relevant.
- Repeat every condition; never build a conclusion from one timing.
- Randomize or counterbalance execution order when order can introduce bias.
- Keep setup, allocation, cleanup, and serialization outside the timer unless
  they are explicitly part of the research question.
- Record environment metadata and keep raw samples.
- Report memory ownership, strides, worker counts, and active native thread
  pools when they affect interpretation.
- Treat CPU utilization and hardware counters as supporting evidence, not as a
  substitute for correctness.

### Output Contract

Most completed experiment directories contain:

```text
expXX_name/
├── README.md
├── benchmark.py
├── results/
│   ├── raw.csv
│   ├── summary.csv
│   └── metadata.json
└── figures/
    └── result.png
```

The exact filenames vary when an experiment needs an additional kernel or a
platform-specific command.

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
    <tr>
      <td><strong>Task size determined whether processes paid off</strong></td>
      <td>Four processes were slower through 100K iterations per task, but reached 3.33× speedup at 1M in Experiment 11.</td>
      <td>Process lifecycle and dispatch costs dominated fine-grained work; only the largest sampled task size amortized them.</td>
    </tr>
    <tr>
      <td><strong>Threads overlapped waiting, not Python computation</strong></td>
      <td>Four threads reached 3.98× speedup for waiting tasks but only 0.95× for CPU-bound tasks in Experiment 12.</td>
      <td>Blocking waits released the GIL, while pure-Python bytecode remained effectively limited to one core.</td>
    </tr>
    <tr>
      <td><strong>Process scaling showed diminishing returns</strong></td>
      <td>One, two, four, and eight workers achieved 1.00×, 2.02×, 3.31×, and 3.97× speedup in Experiment 13.</td>
      <td>Parallel execution reduced wall time, but eight-worker efficiency fell to 49.7% as fixed and shared costs became more significant.</td>
    </tr>
    <tr>
      <td><strong>NumPy ufunc work overlapped across Python threads</strong></td>
      <td>Four threads achieved 3.50× speedup and 349.0% process CPU utilization in Experiment 14.</td>
      <td>The numeric <code>sin</code> ufunc released the GIL during native work, allowing independent tasks to use several cores.</td>
    </tr>
    <tr>
      <td><strong>Native BLAS threading provided sublinear speedup</strong></td>
      <td>Eight BLAS threads achieved 3.06× speedup and 737.7% process CPU utilization in Experiment 15.</td>
      <td>OpenBLAS used several cores, but coordination and shared hardware resources limited scaling.</td>
    </tr>
    <tr>
      <td><strong>Nested thread pools eventually oversubscribed the CPU</strong></td>
      <td>The 8×8 Python/BLAS condition was 17.0% slower than 8×4, while median context switches rose from 1,643 to 2,347 in Experiment 16.</td>
      <td>Additional native threads increased scheduling activity without proportional useful work after the workload reached CPU saturation.</td>
    </tr>
    <tr>
      <td><strong>NumPy views avoided payload-sized allocation</strong></td>
      <td>For a 2048² float64 array, copying took 9.30 ms and allocated 32.0005 MiB; slicing and <code>.view()</code> took 25–30 µs and allocated less than 0.6 KiB in Experiment 17.</td>
      <td>Views created small metadata objects that shared the source buffer, while copying duplicated every element into independently owned storage.</td>
    </tr>
    <tr>
      <td><strong>Transpose and materialization were separate costs</strong></td>
      <td>At 2048², <code>.T</code> took 15 µs and 188 traced bytes, while a contiguous copy took 77.84 ms and 32.0002 MiB in Experiment 18.</td>
      <td>The view changed metadata and shared storage; materialization copied the payload, and did not improve the measured NumPy reduction.</td>
    </tr>
    <tr>
      <td><strong>Deferring cyclic GC exchanged memory for a small timing gain</strong></td>
      <td>Disabling GC improved the measured allocation phase by 1.03×, while traced peak memory rose from 0.78 MiB to 29.01 MiB in Experiment 19.</td>
      <td>Collection work moved outside the timed region; unreachable cycles were not made free.</td>
    </tr>
    <tr>
      <td><strong>Boxed Python integers carried substantial representation cost</strong></td>
      <td>At one million values, <code>list[int]</code> used about 36.00 bytes per element and an <code>int64</code> ndarray used 8.00 in Experiment 20.</td>
      <td>The list stored references to separately allocated integer objects; NumPy stored fixed-width values in one buffer.</td>
    </tr>
    <tr>
      <td><strong>Runtime comparisons require both runtimes</strong></td>
      <td>Experiment 21 recorded a 0.2637 s CPython median, but PyPy was unavailable on the reference host.</td>
      <td>The harness reports missing runtime coverage instead of turning a one-runtime measurement into a cross-runtime claim.</td>
    </tr>
    <tr>
      <td><strong>Concurrent I/O overlapped waiting effectively</strong></td>
      <td>Threads reached 19.28× and asyncio 72.96× sequential speed for 100 synthetic waits in Experiment 22.</td>
      <td>Both models overlapped waiting; asyncio scheduled all waits without limiting concurrency to a 20-worker pool.</td>
    </tr>
    <tr>
      <td><strong>Separating shared writes improved the observed timing</strong></td>
      <td>Cache-line-separated slots were 1.34× faster than adjacent slots in Experiment 23.</td>
      <td>The result is consistent with reduced coherence contention, but Linux hardware counters are still needed for stronger attribution.</td>
    </tr>
    <tr>
      <td><strong>Larger samples narrowed estimated uncertainty</strong></td>
      <td>For one randomized condition, the approximate 95% half-width fell from 0.000507 s at five samples to 0.000288 s at 30 in Experiment 24.</td>
      <td>Repetition and execution order are parts of the experiment, not administrative details.</td>
    </tr>
    <tr>
      <td><strong>The first CPU run differed from the warm distribution</strong></td>
      <td>The first run was 1.051× slower than the warm-run median in Experiment 25.</td>
      <td>Cold state and system dynamics should be measured before choosing a warm-up policy.</td>
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
| 11 | [Task Size and Process Overhead](experiments/exp11_task_size_process_overhead/README.md) | When does useful computation outweigh process overhead? | Complete |
| 12 | [CPU-bound vs I/O-bound](experiments/exp12_cpu_vs_io_bound/README.md) | For which kind of work does threading help? | Complete |
| 13 | [Worker Count Scaling](experiments/exp13_worker_count_scaling/README.md) | How does performance change as process workers increase? | Complete |
| 14 | [NumPy and the GIL](experiments/exp14_numpy_and_gil/README.md) | Can NumPy operations execute concurrently in Python threads? | Complete |
| 15 | [BLAS Threading](experiments/exp15_blas_threading/README.md) | How does the native BLAS thread count affect matrix multiplication? | Complete |
| 16 | [Oversubscription](experiments/exp16_oversubscription/README.md) | Why can combining Python and BLAS thread pools make a workload slower? | Complete |
| 17 | [Memory Copy vs View](experiments/exp17_memory_copy_vs_view/README.md) | How different are the creation-time and memory costs of copies and views? | Complete |
| 18 | [Transpose Cost](experiments/exp18_transpose_cost/README.md) | How do transpose creation and later traversal costs differ? | Complete |
| 19 | [Garbage Collection Overhead](experiments/exp19_garbage_collection_overhead/README.md) | What time and memory trade-off does cyclic collection create? | Complete |
| 20 | [CPython Object Overhead](experiments/exp20_cpython_object_overhead/README.md) | How different are the memory costs of boxed Python and fixed-width NumPy integers? | Complete |
| 21 | [PyPy vs CPython](experiments/exp21_pypy_vs_cpython/README.md) | How do interpreter choice and JIT warm-up affect loop performance? | Harness complete; PyPy measurement pending |
| 22 | [Async I/O vs Threading](experiments/exp22_async_io_vs_threading/README.md) | How do threads and asyncio overlap I/O waiting? | Complete |
| 23 | [False Sharing](experiments/exp23_false_sharing/README.md) | Does cache-line separation improve concurrent shared-memory writes? | Timing complete; Linux counters pending |
| 24 | [Benchmark Stability](experiments/exp24_benchmark_stability/README.md) | How do sample count and execution order affect result stability? | Complete |
| 25 | [CPU Warm-up and Frequency Scaling](experiments/exp25_cpu_warmup_frequency_scaling/README.md) | How does the first run differ from the warm-run distribution? | Complete |

## 6. Reproducing the Study

### Requirements

- Python 3.13 or 3.14
- [`uv`](https://docs.astral.sh/uv/) for environment and dependency management
- Linux and `perf` for Experiments 08 and 23 hardware counters
- PyPy for the cross-runtime portion of Experiment 21

### Setup

```bash
git clone <repository-url>
cd Python_Exp
uv sync
```

`uv sync` installs both runtime and development dependencies from `uv.lock`.
The project currently targets Python 3.13 and 3.14.

### Run an experiment

```bash
uv run python experiments/exp07_vectorization_vs_python_loops/benchmark.py
```

Most benchmarks also provide a smaller smoke-test configuration:

```bash
uv run python experiments/exp07_vectorization_vs_python_loops/benchmark.py --quick
```

Use an experiment's `--help` output to inspect its available parameters:

```bash
uv run python experiments/exp19_garbage_collection_overhead/benchmark.py --help
```

### Verify the repository

```bash
uv run pytest
uv run ruff check .
uv run mypy experiments
```

The current experiment modules share repeated filenames such as
`benchmark.py`. If a local mypy configuration reports duplicate module names,
run it with explicit package bases:

```bash
uv run mypy --explicit-package-bases experiments
```

Generated measurements and figures belong to their experiment directories. Consult the experiment README before comparing values across machines.

## 7. Interpretation and Limitations

The experiments favor understandable controlled comparisons over comprehensive hardware characterization. Reference measurements were collected on one environment per experiment. CPU frequency, scheduling, thermal state, cache history, page placement, compiler decisions, library versions, and background activity can change the observed ratios.

Several studies infer memory-locality effects from timing and stride metadata. Such evidence is consistent with a cache explanation but does not establish cache misses as the sole cause. Experiment 08 explicitly measures generic cache events, although those events also vary by CPU and kernel mapping.

The appropriate conclusion is therefore not that one fixed speedup applies everywhere. It is that data representation, execution layer, working-set size, and access order must be measured together.

## 8. Repository Structure

```text
Python_Exp/
├── README.md
├── pyproject.toml
├── uv.lock
├── experiments/
│   ├── exp01_list_traversal/
│   ├── ...
│   └── exp25_cpu_warmup_frequency_scaling/
├── tests/
└── src/
```

## 9. Current Conclusion

The experiments completed so far support a layered view of Python performance:

<div align="center">

**Workload → Python runtime → data representation → memory access → parallel runtime → hardware**

</div>

Optimizing only the visible loop can miss the actual bottleneck. Pure Python
code may be interpreter- or GIL-bound; compiled code may become
locality-bound; contiguous bulk operations may become bandwidth-bound.

Threads helped when work waited or released the GIL, but did not parallelize
the measured pure-Python CPU loop. Separate processes enabled CPU parallelism,
although small tasks could not recover process lifecycle costs. Native NumPy
and BLAS kernels used multiple cores, while nested Python and BLAS pools
eventually oversubscribed the CPU.

Data ownership and lifetime were equally important. Views avoided
payload-sized allocation but could preserve unfavorable strides. A transpose
was cheap metadata, while materializing it copied the complete payload.
Disabling cyclic GC made one allocation phase only 2.8% faster while increasing
traced peak memory by roughly 37×. A million boxed Python integers required
about 4.5× the accounted memory of an `int64` ndarray.

Finally, the measurement process affected what could responsibly be claimed.
More samples narrowed estimated uncertainty, the first CPU run differed from
the warm distribution, absent PyPy prevented a runtime comparison, and
false-sharing timing still required hardware-counter confirmation.

Reliable performance work therefore requires a controlled question,
equivalent work, correctness checks, explicit ownership and worker-pool
information, raw samples, environment metadata, and conclusions limited to the
evidence actually collected.

---

<div align="center">
  <sub>This repository is intentionally iterative. Results are revised as experiments, platforms, and measurement methods improve.</sub>
</div>
