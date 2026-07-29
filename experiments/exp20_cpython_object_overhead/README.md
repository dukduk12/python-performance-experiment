# Experiment 20 — CPython Object Overhead

[English](#english) · [한국어](#한국어)

![Bytes per element of list[int] and ndarray[int64]](figures/object_overhead.png)

> **Key result:** at 1,000,000 elements, `list[int]` accounts for approximately
> **36.00 B/element**, while an owning NumPy `ndarray[int64]` accounts for
> **8.00 B/element**. Under this experiment's accounting model, the list is
> about **4.50× larger**.

---

## English

### Overview

This experiment compares the structural memory cost of storing the same integer
sequence in two representations:

- CPython `list[int]`: a variable-sized array of references to boxed Python
  integer objects
- NumPy `ndarray[int64]`: a small array object owning one contiguous buffer of
  fixed-width 64-bit integers

The benchmark does not measure execution time or process RSS. It uses
`sys.getsizeof()` to build an explicitly defined, reproducible accounting total.

### Why the Representations Differ

A Python list does not store integer values directly. Conceptually, it stores
one pointer per slot, and every pointed-to Python integer has its own object
header and value storage.

```text
list[int]
┌────────────── list object and pointer slots ──────────────┐
│  ptr ──► PyLong(0)  ptr ──► PyLong(1)  ptr ──► ...       │
└───────────────────────────────────────────────────────────┘

ndarray[int64]
┌──── ndarray metadata ────┐  ┌── contiguous data buffer ──┐
│ shape, dtype, strides... │  │ 0 │ 1 │ 2 │ ... │ n - 1   │
└──────────────────────────┘  └─────────────────────────────┘
```

For the reference 64-bit CPython build, the observed asymptotic costs are:

```text
list[int]       ≈ 8-byte reference + 28-byte PyLong = 36 B/element
ndarray[int64]  = 8-byte fixed-width value          =  8 B/element
```

The constant-size container metadata is divided across more elements as the
sequence grows, so bytes per element approach these values.

### Research Question

How much total and per-element memory does each representation account for as
the number of integers increases?

### Hypothesis

The owning `ndarray[int64]` should approach 8 bytes per element because its
payload uses one fixed-width value per element. The Python list should remain
near 36 bytes per element on the reference build because it accounts for both
the list's pointer slots and a separate `PyLong` object for each value.

### Experimental Setup

- Runtime: CPython 3.13.5, 64-bit
- NumPy: 2.4.6
- Reference platform: Windows 11
- Values: `0` through `n - 1`
- Sizes: 1,000, 100,000, and 1,000,000 elements
- Python representation: `list(range(n))`
- NumPy representation: `np.arange(n, dtype=np.int64)`
- Measurement API: `sys.getsizeof()`
- Repetitions: one deterministic structural measurement per size

#### Variables

| Type | Variables |
| --- | --- |
| Independent | Representation and element count |
| Dependent | Container bytes, payload bytes, total bytes, bytes per element |
| Controlled | Integer sequence, NumPy dtype, measurement API, interpreter process |

This is a size-accounting experiment rather than a noisy timing benchmark, so
warm-ups, repeated samples, and confidence intervals are not applicable.

### Accounting Method

For a Python list, the benchmark adds the shallow size of the list to the
shallow size of every referenced integer:

```python
list_bytes = sys.getsizeof(values) + sum(
    sys.getsizeof(value) for value in values
)
```

For the owning NumPy array, `sys.getsizeof(array)` includes the array object and
its owned data buffer. The benchmark separates the result for reporting:

```python
container_bytes = sys.getsizeof(array) - array.nbytes
payload_bytes = array.nbytes
total_bytes = sys.getsizeof(array)
```

Bytes per element are calculated as:

```text
total bytes / element count
```

### Reproduction

From the repository root, install the locked dependencies and run the complete
experiment:

```bash
uv sync
uv run python experiments/exp20_cpython_object_overhead/benchmark.py
```

Run a small smoke test:

```bash
uv run python experiments/exp20_cpython_object_overhead/benchmark.py --quick
```

Measure custom positive sizes:

```bash
uv run python experiments/exp20_cpython_object_overhead/benchmark.py \
  --sizes 10000 500000 2000000
```

Write CSV and metadata to another directory:

```bash
uv run python experiments/exp20_cpython_object_overhead/benchmark.py \
  --output-dir tmp/exp20-results
```

`--output-dir` changes the CSV and metadata destination. The figure is always
written to `experiments/exp20_cpython_object_overhead/figures/`.

### Results

| Representation | Elements | Container | Payload | Total | Bytes/element |
| --- | ---: | ---: | ---: | ---: | ---: |
| `list[int]` | 1,000 | 8,056 B | 28,000 B | 36,056 B | 36.056 |
| `ndarray[int64]` | 1,000 | 112 B | 8,000 B | 8,112 B | 8.112 |
| `list[int]` | 100,000 | 800,056 B | 2,800,000 B | 3,600,056 B | 36.00056 |
| `ndarray[int64]` | 100,000 | 112 B | 800,000 B | 800,112 B | 8.00112 |
| `list[int]` | 1,000,000 | 8,000,056 B | 28,000,000 B | 36,000,056 B | 36.000056 |
| `ndarray[int64]` | 1,000,000 | 112 B | 8,000,000 B | 8,000,112 B | 8.000112 |

At one million elements:

```text
36,000,056 / 8,000,112 ≈ 4.50
```

The fixed 112-byte ndarray overhead is visible at 1,000 elements but becomes
negligible at larger sizes. The list's per-element result remains close to 36
bytes because both its pointer storage and the accounted integer objects scale
with `n`.

### Generated Artifacts

- `results/summary.csv`: measurements for every representation and size
- `results/metadata.json`: Python, NumPy, platform, and accounting description
- `figures/object_overhead.png`: bytes-per-element comparison on a log-scaled
  element-count axis

Running the benchmark overwrites these generated artifacts for the requested
sizes and current environment.

### Interpretation

The result supports the hypothesis and illustrates the cost of generality.
Python integers provide arbitrary precision and full object semantics, while a
NumPy `int64` uses a fixed-width representation optimized for dense numerical
data.

The result does **not** mean that a NumPy array is always the correct
replacement for a list. A list can contain heterogeneous objects and supports
general Python object behavior. An `int64` array has a fixed dtype and a bounded
numeric range. The comparison is useful when either representation can satisfy
the workload's semantics.

### Threats to Validity

- `sys.getsizeof()` reports shallow object size, not process RSS, allocator
  arena usage, temporary allocations, or fragmentation.
- The list total deliberately assumes exclusive ownership and charges the full
  shallow size of every referenced integer. Interned, cached, or otherwise
  shared integers make this different from incremental process memory.
- The observed sizes are implementation details of the reference CPython,
  NumPy, operating system, architecture, and build. Other versions can differ.
- Larger Python integers may require additional `PyLong` digits and therefore
  more than 28 bytes.
- NumPy views do not own their underlying buffer; applying the same ownership
  interpretation to a view would require accounting for the base array.
- `int64` is not semantically equivalent to Python's arbitrary-precision
  integer for values outside its representable range.

### Conclusion

Under a transparent shallow-container-plus-elements accounting model,
`list[int]` converges to about 36 bytes per element and an owning
`ndarray[int64]` converges to 8 bytes per element on the reference system.
Dense fixed-width storage therefore requires about 4.5× less accounted memory
for this integer sequence.

### Future Work

- Compare `float`, `bool`, strings, and user-defined Python objects.
- Compare NumPy dtypes such as `int8`, `int32`, `float32`, and `object`.
- Measure process RSS and allocation deltas alongside structural accounting.
- Separate cached/shared integers from exclusively allocated integers.
- Compare `array.array`, packed buffers, pandas nullable dtypes, and Arrow.
- Repeat across CPython versions, PyPy, operating systems, and architectures.

---

## 한국어

### 개요

이 실험은 같은 정수 수열을 다음 두 표현에 저장했을 때의 구조적 메모리 비용을
비교한다.

- CPython `list[int]`: 별도의 Python 정수 객체를 가리키는 참조 배열
- NumPy `ndarray[int64]`: 고정 폭 64-bit 정수를 하나의 연속 buffer에 저장하는
  배열 객체

이 benchmark는 실행 시간이나 process RSS를 측정하지 않는다.
`sys.getsizeof()`를 이용해 명시적으로 정의한 귀속 메모리(accounted memory)를
재현 가능하게 계산한다.

### 표현 방식에 따라 크기가 다른 이유

Python list는 정숫값 자체를 slot에 저장하지 않는다. 각 slot에는 정수 객체를
가리키는 pointer가 있고, 각 정수는 object header와 값 저장 공간을 가진 별도
`PyLong` 객체다.

반면 `ndarray[int64]`는 dtype, shape, stride 등의 metadata를 가진 작은 배열
객체와 원소당 정확히 8 byte를 사용하는 연속 data buffer로 구성된다.

기준 64-bit CPython 환경에서 관찰한 점근적 비용은 다음과 같다.

```text
list[int]       ≈ 8-byte 참조 + 28-byte PyLong = 원소당 36 B
ndarray[int64]  = 8-byte 고정 폭 값            = 원소당  8 B
```

원소 수가 커질수록 고정 크기 metadata가 많은 원소에 분산되므로 원소당 byte는
위 값에 가까워진다.

### 연구 질문

정수 개수가 증가할 때 두 표현의 전체 메모리와 원소당 귀속 메모리는 각각
얼마인가?

### 가설

자체 buffer를 소유한 `ndarray[int64]`는 원소당 8 byte에 수렴할 것이다.
Python list는 pointer slot과 별도 `PyLong` 객체를 모두 계산하므로 기준
환경에서 원소당 약 36 byte를 유지할 것이다.

### 실험 환경

- Runtime: 64-bit CPython 3.13.5
- NumPy: 2.4.6
- 기준 platform: Windows 11
- 값의 범위: `0`부터 `n - 1`
- 원소 수: 1,000 / 100,000 / 1,000,000
- Python 표현: `list(range(n))`
- NumPy 표현: `np.arange(n, dtype=np.int64)`
- 측정 API: `sys.getsizeof()`
- 반복 횟수: 크기별 1회의 deterministic 구조 측정

#### 변수

| 구분 | 변수 |
| --- | --- |
| 독립 변수 | 자료 표현, 원소 수 |
| 종속 변수 | Container byte, payload byte, 전체 byte, 원소당 byte |
| 통제 변수 | 정수 수열, NumPy dtype, 측정 API, interpreter process |

시간 변동을 측정하는 benchmark가 아니므로 warm-up, 반복 sample, 신뢰구간은
적용하지 않았다.

### 메모리 계산 방식

Python list는 list 자체의 shallow size와 참조하는 모든 정수의 shallow size를
합산한다.

```python
list_bytes = sys.getsizeof(values) + sum(
    sys.getsizeof(value) for value in values
)
```

자체 buffer를 소유한 NumPy 배열은 `sys.getsizeof(array)`에 배열 객체와 data
buffer가 포함된다. 결과 표에서는 다음과 같이 분리한다.

```python
container_bytes = sys.getsizeof(array) - array.nbytes
payload_bytes = array.nbytes
total_bytes = sys.getsizeof(array)
```

원소당 byte는 `전체 byte / 원소 수`로 계산한다.

### 재현 방법

Repository root에서 lock file 기준 dependency를 설치하고 전체 실험을
실행한다.

```bash
uv sync
uv run python experiments/exp20_cpython_object_overhead/benchmark.py
```

빠른 smoke test:

```bash
uv run python experiments/exp20_cpython_object_overhead/benchmark.py --quick
```

원하는 양의 정수 크기로 측정:

```bash
uv run python experiments/exp20_cpython_object_overhead/benchmark.py \
  --sizes 10000 500000 2000000
```

CSV와 metadata의 출력 위치 지정:

```bash
uv run python experiments/exp20_cpython_object_overhead/benchmark.py \
  --output-dir tmp/exp20-results
```

`--output-dir`은 CSV와 metadata 경로만 변경한다. Figure는 항상
`experiments/exp20_cpython_object_overhead/figures/`에 저장된다.

### 결과

| 표현 | 원소 수 | Container | Payload | 전체 | 원소당 byte |
| --- | ---: | ---: | ---: | ---: | ---: |
| `list[int]` | 1,000 | 8,056 B | 28,000 B | 36,056 B | 36.056 |
| `ndarray[int64]` | 1,000 | 112 B | 8,000 B | 8,112 B | 8.112 |
| `list[int]` | 100,000 | 800,056 B | 2,800,000 B | 3,600,056 B | 36.00056 |
| `ndarray[int64]` | 100,000 | 112 B | 800,000 B | 800,112 B | 8.00112 |
| `list[int]` | 1,000,000 | 8,000,056 B | 28,000,000 B | 36,000,056 B | 36.000056 |
| `ndarray[int64]` | 1,000,000 | 112 B | 8,000,000 B | 8,000,112 B | 8.000112 |

백만 원소에서의 비율은 다음과 같다.

```text
36,000,056 / 8,000,112 ≈ 4.50
```

고정 크기인 ndarray의 112-byte overhead는 1,000개 구간에서는 보이지만 원소
수가 증가하면 거의 무시할 수 있다. List는 pointer와 정수 객체가 모두 `n`에
비례해 증가하므로 원소당 약 36 byte를 유지한다.

### 생성 파일

- `results/summary.csv`: 표현과 크기별 측정값
- `results/metadata.json`: Python, NumPy, platform, 계산 방식
- `figures/object_overhead.png`: log scale 원소 수에 따른 원소당 byte

Benchmark를 다시 실행하면 지정한 크기와 현재 환경의 결과로 기존 생성 파일을
덮어쓴다.

### 해석

결과는 가설과 일치하며 Python 객체가 제공하는 일반성의 비용을 보여준다.
Python 정수는 arbitrary precision과 완전한 객체 semantics를 제공하지만,
NumPy `int64`는 조밀한 수치 데이터를 위해 고정 폭 표현을 사용한다.

그렇다고 NumPy 배열이 항상 list의 올바른 대체재라는 뜻은 아니다. List는
서로 다른 종류의 객체를 담고 일반적인 Python 객체 동작을 지원한다.
`int64` 배열은 dtype이 고정되고 표현 가능한 숫자 범위도 제한된다. 이 비교는
두 표현이 모두 workload의 의미를 충족할 때 유용하다.

### 타당성 위협

- `sys.getsizeof()`는 shallow object size를 반환한다. Process RSS, allocator
  arena, 임시 allocation, fragmentation을 포함하지 않는다.
- List 계산은 각 정수를 독점 소유한다고 가정해 모든 정수의 shallow size를
  귀속한다. Interning, small-integer cache 또는 다른 공유 참조가 있으면 실제
  process memory 증가량과 다르다.
- 측정값은 기준 CPython, NumPy, 운영체제, architecture와 build의 구현
  세부사항이다. 다른 환경에서는 달라질 수 있다.
- 큰 Python 정수는 추가 `PyLong` digit이 필요해 28 byte보다 커질 수 있다.
- NumPy view는 base array의 buffer를 공유하므로 동일한 소유권 계산을 그대로
  적용할 수 없다.
- `int64`는 표현 범위 밖의 값에서 Python arbitrary-precision 정수와 의미가
  같지 않다.

### 결론

Shallow container와 원소 크기를 합산하는 명시적 계산 방식에서 기준 시스템의
`list[int]`는 원소당 약 36 byte, 자체 buffer를 소유한 `ndarray[int64]`는
원소당 8 byte에 수렴했다. 이 정수 수열에서는 고정 폭 연속 저장 방식이 약
4.5배 적은 귀속 메모리를 사용했다.

### 향후 작업

- `float`, `bool`, 문자열과 사용자 정의 Python 객체 비교
- `int8`, `int32`, `float32`, `object` 등 NumPy dtype 비교
- 구조적 계산과 process RSS 및 allocation delta 동시 측정
- Cached/shared integer와 독점 할당 integer 분리
- `array.array`, packed buffer, pandas nullable dtype, Arrow 비교
- 여러 CPython version, PyPy, 운영체제와 architecture에서 반복
