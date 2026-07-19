# Experiment 08 — Cache Miss Measurement

[English](#english) · [한국어](#한국어)

---

## English

### 1. Experiment Overview

This experiment traverses the same C-order `float64` array in row-first and column-first order. It uses Linux `perf` hardware counters to examine whether differences in execution time occur alongside differences in cache references and cache misses.

### 2. Research Question

When the array and computation are held constant, does column-first traversal produce a higher cache miss rate and a longer execution time than row-first traversal?

### 3. Background

Elements in each row of a C-order array are contiguous in memory. Row-first traversal reads adjacent addresses and can make effective use of cache lines and hardware prefetching. Column-first traversal jumps by one row on each access, which can reduce spatial locality.

The generic `cache-references` and `cache-misses` events exposed by `perf` do not necessarily represent the same cache level on every CPU. Their precise mapping depends on the processor and Linux kernel.

### 4. Hypothesis

Column-first traversal is expected to produce more cache misses, a higher miss rate, and a longer execution time. The difference should be clearer when the array is larger than the available CPU caches. The two metrics may not be perfectly proportional because prefetching, TLB behavior, CPU frequency, and system load can also affect the result.

### 5. Experimental Setup and Variables

- Tools: CPython, NumPy, Numba, and Linux `perf`
- Data: C-contiguous square `float64` ndarray
- Default size: `4096 × 4096` elements (128 MiB)
- Conditions: `row_first` and `column_first`
- Workload: sum every array element
- Default protocol: two warmups, five measured traversals per `perf` invocation, and seven invocations per condition
- Condition order randomized within every repetition using seed `20260719`
- Recommended environment: bare-metal Linux
- CPU information: relevant to interpretation; record `lscpu`, the CPU governor, and `perf --version`

The independent variable is traversal order. The dependent variables are median execution time, cache references, cache misses, cache miss rate, and slowdown relative to row-first traversal. Array size, dtype, memory order, values, calculation, Numba compilation mode, warmups, repetitions, random seed, machine, and OS configuration are controlled variables.

Virtual machines and WSL may not expose usable hardware counters. If `perf` reports a permission error, inspect the distribution's `kernel.perf_event_paranoid` policy. The benchmark does not modify system security settings.

```bash
uv run python experiments/exp08_cache_miss_measurement/benchmark.py
uv run python experiments/exp08_cache_miss_measurement/benchmark.py --quick
```

### 6. Benchmark Methodology and Implementation Plan

The two `@njit(cache=True)` functions in `kernel.py` sum the same array in different traversal orders. Each subprocess creates the array, warms up the selected function, verifies its checksum, and measures individual traversals with `time.perf_counter()`.

`benchmark.py` runs each condition in a separate process under:

```bash
perf stat -x ';' -e cache-references,cache-misses
```

Condition order is randomized in every repetition to reduce time-order, temperature, and frequency bias. The median of seven invocations is the primary statistic. Sample standard deviation is also stored for execution time. Each invocation's miss rate is calculated as `cache misses / cache references × 100`, after which the median miss rate is reported.

Implementation order:

1. Implement equivalent row-first and column-first Numba kernels.
2. Validate both kernels using the expected checksum.
3. Warm up the selected kernel and measure repeated traversals.
4. Execute each workload with `perf stat` and parse its delimited output.
5. Randomize condition order and collect repeated measurements.
6. Write raw data, summary statistics, and environment metadata.
7. Test counter parsing and summary calculations independently of `perf`.

Numba compilation, Python startup, array allocation, and warmup are excluded from the traversal timer but remain inside the whole-process `perf` counter scope. These common costs are diluted by repeated measured traversals but are not completely removed.

### 7. Measurements and Visualization

- `results/raw.csv`: condition, repetition, execution order, times, cache references, cache misses, and miss rate
- `results/summary.csv`: median time, time standard deviation, median counters, median miss rate, and slowdown
- `results/metadata.json`: Python and platform information, array configuration, repetition settings, seed, events, and counter scope

The recommended visualization contains:

- A bar chart with traversal order on the x-axis and median execution time in milliseconds on the y-axis
- A bar chart with traversal order on the x-axis and median cache miss rate on the y-axis
- Optionally, a scatter plot of execution time against miss rate for individual invocations

The time and miss-rate charts should be interpreted together to determine whether the slower traversal also produces more cache misses.

### 8. Expected Results

Row-first traversal is expected to have a lower cache miss rate and a shorter execution time. A small difference or a reversal could indicate that the array fits in cache, the hardware prefetcher handles the access pattern effectively, the generic events map differently on the CPU, or virtualization and background load affected the counters. No result is assumed before measurement.

### 9. Results

No hardware-counter results are committed yet because the current development environment is Windows. Run the benchmark on Linux to generate `raw.csv`, `summary.csv`, and `metadata.json`, then record the measured values here.

### 10. Discussion

The execution-time difference and cache-counter difference must be evaluated together. A higher cache miss rate in the slower condition would be consistent with the locality hypothesis, but it would not prove that cache misses are the only cause. TLB misses, memory bandwidth, address calculation, CPU frequency, and other microarchitectural behavior may also contribute.

The whole-process counter scope must also be considered because it includes common Python startup, allocation, and warmup activity outside the timed traversals.

### 11. Conclusion

A conclusion should be written only after collecting hardware counters on a documented Linux system. The experiment is designed to determine whether poorer traversal locality, higher cache miss activity, and longer execution time appear together under controlled conditions.

### 12. Threats to Validity and Future Work

Generic `cache-misses` events do not refer to an identical cache level on every processor. Hardware counters may be unavailable, multiplexed, or restricted by the operating system. Python and NumPy startup, allocation, and warmup are included in the process-wide counters. Numba-generated code, hardware prefetchers, TLB behavior, CPU frequency, thermals, and background activity can affect the result.

Future work may compare CPU-specific native L1 and LLC events, isolate only the region of interest using a lower-level counter API, pin the process to a CPU, and test multiple array sizes. Those extensions are outside the scope of this experiment.

---

## 한국어

### 1. 실험 개요

동일한 C-order `float64` 배열을 행 우선과 열 우선 순서로 순회한다. Linux `perf` hardware counter를 사용하여 실행 시간 차이가 cache reference 및 cache miss 차이와 함께 나타나는지 확인한다.

### 2. 연구 질문

배열과 계산을 동일하게 통제했을 때 열 우선 순회는 행 우선 순회보다 cache miss rate가 높고 실행 시간이 긴가?

### 3. 배경

C-order 배열에서 한 행의 원소들은 메모리에 연속으로 저장된다. 행 우선 순회는 인접한 주소를 읽으므로 cache line과 hardware prefetch를 활용하기 쉽다. 열 우선 순회는 접근할 때마다 한 행 크기만큼 건너뛰기 때문에 공간 지역성이 낮아질 수 있다.

`perf`가 제공하는 generic event인 `cache-references`와 `cache-misses`는 모든 CPU에서 동일한 cache level을 의미하지 않는다. 정확한 event 매핑은 CPU와 Linux kernel에 따라 달라진다.

### 4. 가설

열 우선 순회에서 cache miss 수와 miss rate가 더 높고 실행 시간도 더 길 것으로 예상한다. 배열이 CPU cache보다 충분히 클 때 차이가 뚜렷할 가능성이 높다. 다만 prefetcher, TLB, CPU frequency와 시스템 부하도 결과에 영향을 주므로 두 측정값이 완전히 비례한다고 가정하지 않는다.

### 5. 실험 환경과 변수

- 도구: CPython, NumPy, Numba, Linux `perf`
- 데이터: C-contiguous 정사각 `float64` ndarray
- 기본 크기: `4096 × 4096` 원소(128 MiB)
- 조건: `row_first`, `column_first`
- 작업: 배열의 모든 원소 합산
- 기본 설정: warmup 2회, `perf` 호출당 측정 순회 5회, 조건별 호출 7회
- 실행 순서: seed `20260719`로 매 반복에서 무작위화
- 권장 환경: bare-metal Linux
- CPU 정보: 결과 해석을 위해 `lscpu`, CPU governor와 `perf --version` 기록 권장

독립 변수는 순회 방향이다. 종속 변수는 중앙 실행 시간, cache references, cache misses, miss rate와 행 우선 대비 slowdown이다. 배열 크기·dtype·저장 순서·값, 합산 연산, Numba compilation mode, warmup·반복 횟수, random seed, 머신과 OS 설정을 통제한다.

VM이나 WSL에서는 hardware counter가 제공되지 않을 수 있다. 권한 오류가 발생하면 배포판의 `kernel.perf_event_paranoid` 정책을 확인한다. 실험 코드는 시스템 보안 설정을 자동으로 변경하지 않는다.

```bash
uv run python experiments/exp08_cache_miss_measurement/benchmark.py
uv run python experiments/exp08_cache_miss_measurement/benchmark.py --quick
```

### 6. 벤치마크 방법과 구현 계획

`kernel.py`의 두 `@njit(cache=True)` 함수가 같은 배열을 서로 다른 순서로 합산한다. 각 subprocess는 배열을 생성하고 선택된 함수를 warmup한 뒤 checksum을 검사하며, `time.perf_counter()`로 개별 순회 시간을 측정한다.

`benchmark.py`는 각 조건을 별도 프로세스로 다음 명령 아래에서 실행한다.

```bash
perf stat -x ';' -e cache-references,cache-misses
```

시간 경과, 발열과 frequency 편향을 줄이기 위해 매 반복에서 조건 순서를 무작위화한다. 조건별 7회 측정의 중앙값을 대표값으로 사용하며 실행 시간의 표본 표준편차도 저장한다. 각 실행의 miss rate를 `cache misses / cache references × 100`으로 계산한 뒤 중앙값을 보고한다.

구현 순서는 다음과 같다.

1. 동등한 행 우선·열 우선 Numba kernel 구현
2. 예상 checksum을 이용한 정확성 검증
3. kernel warmup 및 반복 순회 시간 측정
4. `perf stat` 실행과 구분자 형식 출력 파싱
5. 조건 순서 무작위화 및 반복 측정
6. raw data, summary와 환경 metadata 저장
7. `perf`와 독립적으로 counter parser 및 통계 계산 테스트

Numba compilation, Python startup, 배열 할당과 warmup은 순회 시간에서 제외되지만 whole-process `perf` counter 범위에는 포함된다. 반복 순회로 이러한 공통 비용을 희석하지만 완전히 제거하지는 못한다.

### 7. 측정값과 시각화

- `results/raw.csv`: 조건, 반복, 실행 순서, 시간, cache references/misses와 miss rate
- `results/summary.csv`: 중앙 시간, 시간 표준편차, 중앙 counter, 중앙 miss rate와 slowdown
- `results/metadata.json`: Python·platform, 배열 설정, 반복 설정, seed, event와 counter 범위

권장 그래프는 다음과 같다.

- x축 순회 방향, y축 중앙 실행 시간(ms)의 막대그래프
- x축 순회 방향, y축 중앙 cache miss rate(%)의 막대그래프
- 선택적으로 개별 실행의 miss rate와 실행 시간 scatter plot

두 막대그래프를 함께 확인하여 느린 순회 조건에서 cache miss도 증가하는지 해석한다.

### 8. 예상 결과

행 우선 순회가 더 낮은 cache miss rate와 짧은 실행 시간을 보일 것으로 예상한다. 차이가 작거나 반대라면 배열이 cache에 들어갔거나, hardware prefetcher가 접근 패턴을 효과적으로 처리했거나, CPU의 generic event 매핑·가상화·background load가 counter에 영향을 주었을 수 있다. 실측 전에 결과를 확정하지 않는다.

### 9. 결과

현재 개발 환경이 Windows이므로 hardware counter 실측 결과는 아직 기록하지 않았다. Linux에서 benchmark를 실행해 `raw.csv`, `summary.csv`, `metadata.json`을 생성한 뒤 측정값을 이 절에 기록한다.

### 10. 논의

실행 시간 차이와 cache counter 차이를 함께 평가해야 한다. 느린 조건에서 높은 cache miss rate가 관찰된다면 지역성 가설과 일치하지만, cache miss가 유일한 원인임을 증명하지는 않는다. TLB miss, memory bandwidth, 주소 계산, CPU frequency와 다른 microarchitecture 동작도 영향을 줄 수 있다.

또한 whole-process counter에는 측정 순회 밖의 Python startup, 배열 할당과 warmup 활동도 포함된다는 점을 고려해야 한다.

### 11. 결론

문서화된 Linux 환경에서 hardware counter를 수집한 뒤에 결론을 작성한다. 이 실험은 통제된 조건에서 낮은 순회 지역성, 높은 cache miss 활동과 긴 실행 시간이 함께 나타나는지 확인하도록 설계되었다.

### 12. 타당성 위협과 향후 작업

Generic `cache-misses` event는 모든 CPU에서 같은 cache level을 뜻하지 않는다. Hardware counter가 제공되지 않거나 multiplexing되거나 OS 권한으로 제한될 수 있다. 프로세스 단위 counter에는 Python·NumPy startup, allocation과 warmup도 포함된다. Numba 생성 코드, hardware prefetcher, TLB, CPU frequency, 발열과 background activity도 결과에 영향을 준다.

향후에는 CPU별 native L1·LLC event 비교, 더 낮은 수준의 counter API를 이용한 관심 구간 격리, CPU affinity 고정과 여러 배열 크기 측정을 고려할 수 있다. 이러한 확장은 이번 실험의 범위에는 포함하지 않는다.
