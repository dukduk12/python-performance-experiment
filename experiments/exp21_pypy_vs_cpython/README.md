# Experiment 21 — PyPy vs CPython

[English](#english) · [한국어](#한국어)

> **Current status:** the benchmark harness is complete. A second run on Linux
> on August 9, 2026 again found no `pypy3`/`pypy` executable, so the saved
> artifacts still establish a CPython baseline only; they do **not** support a
> PyPy-versus-CPython speed claim.

---

## English

### Overview

This experiment runs the same pure-Python integer loop repeatedly in isolated
interpreter processes. It is designed to compare:

- CPython's execution time for the workload;
- PyPy's execution time after its tracing JIT has had opportunities to optimize
  the hot loop; and
- the change from the first run to the fastest run within each interpreter.

The benchmark automatically uses the Python executable that launched it as the
`cpython` candidate. It also searches `PATH` for `pypy3`, then `pypy`. If PyPy
is not found, the CPython measurement still runs and that absence is recorded
in `metadata.json`.

### Why PyPy May Behave Differently

PyPy can observe frequently executed paths and compile hot operations to
machine code while the process is running. Compilation itself has a cost, so a
short or first execution may not show the eventual benefit. Repeating the loop
inside one long-lived process exposes this warm-up behavior.

This does not imply that PyPy is always faster. Results depend on the workload,
runtime versions, run duration, native-extension use, and machine. This
experiment intentionally studies one narrow, JIT-friendly pure-Python kernel.

### Research Question and Hypothesis

**Question:** for an identical integer loop, how do CPython and PyPy differ in
overall run time and in the improvement between the first and fastest repeat?

**Hypothesis:** PyPy may pay extra cost early, then execute later repeats faster
after JIT compilation. CPython is expected to show a smaller sequential change,
although ordinary timing noise and adaptive runtime behavior can still affect
its repeats.

### Workload

Each repeat evaluates the following recurrence for `n` iterations:

```python
x = 0
for i in range(n):
    x = (x + i * i) % 1_000_000_007
```

The modular reduction keeps the integer bounded and the final `x` is saved as
a checksum. Equal checksums confirm that both interpreters completed the same
logical computation; they are not a proof that every execution detail was
identical.

Default settings:

| Parameter | Default | Purpose |
| --- | ---: | --- |
| Iterations | 2,000,000 | Work performed by each timed repeat |
| Repeats | 7 | Sequential measurements in each interpreter process |
| Timer | `time.perf_counter_ns()` | High-resolution elapsed time |
| Process count | One per interpreter | Keeps each runtime's JIT state isolated |

The parent process launches each available runtime with `-c`. Interpreter
startup and result serialization occur outside the timed region. All repeats
for one interpreter occur in the same child process, so JIT state can persist
between repeats.

### Variables and Metrics

| Kind | Values |
| --- | --- |
| Independent variables | Interpreter and repeat number |
| Dependent variables | Seconds per repeat, median seconds, warm-up ratio |
| Controlled variables | Source string, iteration count, repeat count, checksum algorithm |

For each interpreter, the summary reports:

```text
median_seconds = median(all repeat times)
warmup_ratio   = first repeat time / fastest repeat time
```

A warm-up ratio of `1.00` means that the first run was also the fastest. A value
of `1.50` means that the first run took 1.5 times as long as the fastest run.
The metric is descriptive: with only seven samples, it cannot distinguish JIT
warm-up from scheduler noise, CPU frequency changes, or other system effects.

### Reproduction

Run commands from the repository root. Install the locked project environment:

```bash
uv sync
```

Ensure PyPy is installed separately and its executable is visible on `PATH`:

```bash
pypy3 --version
# On Windows, the executable may instead be named pypy.exe:
pypy --version
```

Run the full benchmark:

```bash
uv run python experiments/exp21_pypy_vs_cpython/benchmark.py
```

Run a quick smoke test. This overrides the other size options with 20,000
iterations and 3 repeats:

```bash
uv run python experiments/exp21_pypy_vs_cpython/benchmark.py --quick
```

Choose a larger workload and more repeats:

```bash
uv run python experiments/exp21_pypy_vs_cpython/benchmark.py \
  --iterations 5000000 \
  --repeats 10
```

Write generated files to a different directory:

```bash
uv run python experiments/exp21_pypy_vs_cpython/benchmark.py \
  --output-dir tmp/exp21-results
```

Use a standard CPython executable to launch the harness. The current discovery
logic labels `sys.executable` as `cpython`, so launching the harness itself with
PyPy would give that executable the wrong label.

### Reference Result

Reference environment recorded in the repository:

- Platform: Windows 11 (`Windows-11-10.0.26200-SP0`)
- CPython executable: project virtual environment
- PyPy available: no
- Iterations per repeat: 2,000,000
- Repeats: 7

| Repeat | CPython time (s) | Checksum |
| ---: | ---: | ---: |
| 1 | 0.2715472 | 347464 |
| 2 | 0.2602126 | 347464 |
| 3 | 0.2557244 | 347464 |
| 4 | 0.2805424 | 347464 |
| 5 | 0.2796747 | 347464 |
| 6 | 0.2636634 | 347464 |
| 7 | 0.2616865 | 347464 |

| Interpreter | Runs | First (s) | Median (s) | First / fastest |
| --- | ---: | ---: | ---: | ---: |
| CPython | 7 | 0.2715472 | 0.2636634 | 1.0619× |
| PyPy | — | — | — | Not installed |

The fastest CPython repeat was `0.2557244 s`; therefore:

```text
0.2715472 / 0.2557244 = 1.0619
```

The first repeat was about 6.2% slower than the fastest repeat. This small
sequence alone should not be interpreted as evidence of CPython warm-up, and no
cross-runtime conclusion is possible until PyPy data is collected on the same
host under the same conditions.

Additional Linux rerun on August 9, 2026:

- Platform: `Linux-7.0.0-28-generic-x86_64-with-glibc2.39`
- CPython executable: `.venv/bin/python3`
- PyPy available: no
- Iterations per repeat: 2,000,000
- Repeats: 7

| Interpreter | Runs | First (s) | Median (s) | First / fastest |
| --- | ---: | ---: | ---: | ---: |
| CPython | 7 | 0.332060745 | 0.32231003 | 1.0389× |
| PyPy | — | — | — | Not installed |

This Linux rerun changed the absolute CPython timing but not the status of the
research question: PyPy was still missing, so no cross-runtime claim can be
made from the checked-in artifacts alone.

### Generated Artifacts

The default destination is `experiments/exp21_pypy_vs_cpython/results/`.

- `raw.csv`: one row per interpreter and repeat, with `interpreter`, `repeat`,
  `seconds`, and `checksum` columns;
- `summary.csv`: run count, first time, median time, and warm-up ratio for each
  detected interpreter; and
- `metadata.json`: platform string, discovered executable paths, and whether
  PyPy was available.

Re-running the benchmark overwrites these three files in the selected output
directory. The executable paths in metadata are environment-specific and may
contain user or machine directory names.

### How to Interpret a Complete Comparison

When both rows are present, compare median times only after checking that:

1. checksums match across every repeat and interpreter;
2. both runtimes used the same iteration and repeat counts;
3. the machine was not under substantial unrelated load; and
4. runtime versions and executable paths were recorded.

The median describes the measured sequence, including early warm-up repeats.
For a stricter steady-state study, add more repeats and report a separately
defined post-warm-up window rather than silently dropping early measurements.

### Limitations and Threats to Validity

- A single arithmetic microkernel does not represent web applications, data
  processing, scientific Python, or object-heavy application code.
- Seven repeats are useful for observation but too few for strong statistical
  claims or confidence intervals.
- The minimum used in `warmup_ratio` is sensitive to one unusually fast sample.
- Interpreter order is fixed, not randomized, so machine state can differ
  between the CPython and PyPy child processes.
- CPU boosting, thermal throttling, antivirus activity, scheduler decisions,
  and background programs can affect elapsed time.
- Startup time is deliberately excluded. This favors analysis of a running
  workload and does not describe command-line programs dominated by startup.
- Repeats share JIT and process state within one runtime, but different
  interpreters run in separate processes and cannot share such state.
- PyPy compatibility and performance may differ for workloads dominated by C
  extension modules; this benchmark uses only the standard library.
- The metadata records executable paths and platform, but not full interpreter
  versions, CPU model, power plan, or per-run system state.
- The harness assumes its launcher is CPython when assigning labels.

### Conclusion

Experiment 21 provides a small, reproducible harness for observing repeated
pure-Python loop performance and potential JIT warm-up across CPython and PyPy.
The checked-in Windows data establishes a CPython median of `0.2636634 s`, and
the August 9, 2026 Linux rerun established `0.32231003 s` on that host. PyPy
was absent in both environments, so the primary cross-runtime research
question remains open.

### Future Work

- Capture PyPy and CPython version strings in metadata.
- Validate that the discovered implementation matches its assigned label.
- Randomize or alternate interpreter order across independent trials.
- Add configurable warm-up runs and a separately reported steady-state window.
- Report dispersion and confidence intervals from multiple fresh processes.
- Add object allocation, string processing, and branch-heavy workloads.
- Compare startup-inclusive latency as a separate experiment.

---

## 한국어

### 개요

이 실험은 동일한 순수 Python 정수 loop를 서로 격리된 interpreter process에서
여러 번 실행한다. 다음 세 가지를 관찰하는 것이 목적이다.

- CPython에서의 workload 실행 시간
- PyPy tracing JIT가 hot loop를 최적화할 기회를 얻은 뒤의 실행 시간
- 각 interpreter에서 첫 실행과 가장 빠른 실행 사이의 변화

Benchmark를 실행한 Python executable은 `cpython` 후보로 사용한다. 그리고
`PATH`에서 `pypy3`, 그다음 `pypy`를 찾는다. PyPy를 찾지 못해도 CPython
측정은 진행하며, PyPy가 없었다는 사실을 `metadata.json`에 기록한다.

### PyPy의 결과가 달라질 수 있는 이유

PyPy는 자주 실행되는 경로를 관찰하고 process 실행 중 hot operation을 machine
code로 compile할 수 있다. Compile 자체에도 비용이 들기 때문에 짧은 실행이나
첫 실행에서는 이점이 드러나지 않을 수 있다. 하나의 process 안에서 loop를
연속 반복하면 이러한 warm-up 동작을 관찰할 수 있다.

그러나 PyPy가 언제나 빠르다는 뜻은 아니다. Workload, runtime version, 실행
시간, native extension 사용 여부와 machine에 따라 결과가 달라진다. 이 실험은
의도적으로 범위를 좁혀 JIT가 최적화하기 쉬운 순수 Python kernel 하나를
측정한다.

### 연구 질문과 가설

**연구 질문:** 동일한 정수 loop에서 CPython과 PyPy의 전체 실행 시간 및 첫
반복 대비 가장 빠른 반복의 개선 정도는 어떻게 다른가?

**가설:** PyPy는 초기에 JIT compile 비용을 부담하지만 이후 반복은 더 빨라질
수 있다. CPython의 순차 변화는 더 작을 것으로 예상하지만, 일반적인 timing
noise와 runtime의 adaptive behavior도 결과에 영향을 줄 수 있다.

### 측정 workload

각 반복은 `n`회에 걸쳐 다음 점화식을 계산한다.

```python
x = 0
for i in range(n):
    x = (x + i * i) % 1_000_000_007
```

Modulo 연산으로 정수 크기를 제한하며 마지막 `x`를 checksum으로 저장한다.
Checksum이 같으면 두 interpreter가 논리적으로 같은 계산을 끝냈음을 확인할 수
있지만, 모든 실행 세부사항이 동일했다는 증명은 아니다.

기본 설정은 다음과 같다.

| 설정 | 기본값 | 의미 |
| --- | ---: | --- |
| Iteration | 2,000,000 | 한 번의 timed repeat에서 수행하는 작업량 |
| Repeat | 7 | Interpreter process 하나에서 연속 측정하는 횟수 |
| Timer | `time.perf_counter_ns()` | 고해상도 경과 시간 측정 |
| Process 수 | Interpreter당 1개 | Runtime별 JIT state 격리 |

Parent process가 사용 가능한 각 runtime을 `-c` option으로 실행한다. Interpreter
startup과 결과 직렬화는 timed region 밖에 있다. 한 interpreter의 모든 반복은
같은 child process에서 실행되므로 반복 사이에 JIT state가 유지될 수 있다.

### 변수와 지표

| 구분 | 내용 |
| --- | --- |
| 독립 변수 | Interpreter, 반복 번호 |
| 종속 변수 | 반복별 초, 중앙값, warm-up ratio |
| 통제 변수 | Source string, iteration 수, repeat 수, checksum algorithm |

Interpreter별 summary 계산식은 다음과 같다.

```text
median_seconds = 모든 반복 시간의 중앙값
warmup_ratio   = 첫 반복 시간 / 가장 빠른 반복 시간
```

Warm-up ratio가 `1.00`이면 첫 실행이 가장 빨랐다는 의미다. `1.50`이면 첫
실행에 가장 빠른 실행의 1.5배 시간이 걸렸다는 뜻이다. 단, 7개 sample로는 JIT
warm-up과 scheduler noise, CPU clock 변화 등의 영향을 구분할 수 없으므로 이
값은 기술적인 관찰 지표로 해석해야 한다.

### 재현 방법

Repository root에서 lock file 기준 환경을 설치한다.

```bash
uv sync
```

PyPy는 별도로 설치해야 하며 executable이 `PATH`에 보여야 한다.

```bash
pypy3 --version
# Windows에서는 executable 이름이 pypy.exe일 수도 있다.
pypy --version
```

전체 benchmark 실행:

```bash
uv run python experiments/exp21_pypy_vs_cpython/benchmark.py
```

빠른 smoke test 실행. `--quick`은 다른 크기 option을 무시하고 20,000 iteration,
3 repeat를 사용한다.

```bash
uv run python experiments/exp21_pypy_vs_cpython/benchmark.py --quick
```

작업량과 반복 횟수 지정:

```bash
uv run python experiments/exp21_pypy_vs_cpython/benchmark.py \
  --iterations 5000000 \
  --repeats 10
```

결과 저장 위치 지정:

```bash
uv run python experiments/exp21_pypy_vs_cpython/benchmark.py \
  --output-dir tmp/exp21-results
```

Harness 자체는 일반 CPython executable로 실행해야 한다. 현재 탐지 logic은
`sys.executable`을 무조건 `cpython`으로 표시하므로, harness를 PyPy로 직접
실행하면 그 executable에 잘못된 label이 붙는다.

### 기준 측정 결과

Repository에 저장된 기준 환경:

- Platform: Windows 11 (`Windows-11-10.0.26200-SP0`)
- CPython executable: project virtual environment
- PyPy 사용 가능 여부: 없음
- 반복당 iteration: 2,000,000
- Repeat: 7회

| 반복 | CPython 시간 (초) | Checksum |
| ---: | ---: | ---: |
| 1 | 0.2715472 | 347464 |
| 2 | 0.2602126 | 347464 |
| 3 | 0.2557244 | 347464 |
| 4 | 0.2805424 | 347464 |
| 5 | 0.2796747 | 347464 |
| 6 | 0.2636634 | 347464 |
| 7 | 0.2616865 | 347464 |

| Interpreter | 실행 수 | 첫 실행 (초) | 중앙값 (초) | 첫 실행 / 최단 실행 |
| --- | ---: | ---: | ---: | ---: |
| CPython | 7 | 0.2715472 | 0.2636634 | 1.0619× |
| PyPy | — | — | — | 미설치 |

가장 빠른 CPython 반복은 `0.2557244초`였으므로 다음과 같이 계산된다.

```text
0.2715472 / 0.2557244 = 1.0619
```

첫 반복은 가장 빠른 반복보다 약 6.2% 느렸다. 이 짧은 sequence만으로 CPython의
warm-up을 입증할 수는 없다. 또한 같은 host와 조건에서 PyPy를 측정하기 전에는
runtime 사이의 성능 결론을 내릴 수 없다.

2026년 8월 9일 Linux 재실행:

- Platform: `Linux-7.0.0-28-generic-x86_64-with-glibc2.39`
- CPython executable: `.venv/bin/python3`
- PyPy 사용 가능 여부: 없음
- 반복당 iteration: 2,000,000
- Repeat: 7회

| Interpreter | 실행 수 | 첫 실행 (초) | 중앙값 (초) | 첫 실행 / 최단 실행 |
| --- | ---: | ---: | ---: | ---: |
| CPython | 7 | 0.332060745 | 0.32231003 | 1.0389× |
| PyPy | — | — | — | 미설치 |

이 Linux 재실행은 CPython 절대 시간은 바꿨지만 연구 질문의 상태는 바꾸지
못했다. PyPy가 여전히 없었기 때문에 저장된 산출물만으로는 runtime 간 비교
주장을 만들 수 없다.

### 생성 파일

기본 저장 위치는 `experiments/exp21_pypy_vs_cpython/results/`이다.

- `raw.csv`: `interpreter`, `repeat`, `seconds`, `checksum`을 담은 반복별 원시값
- `summary.csv`: 탐지된 interpreter별 실행 수, 첫 시간, 중앙값, warm-up ratio
- `metadata.json`: platform, 발견한 executable path, PyPy 사용 가능 여부

Benchmark를 다시 실행하면 선택한 output directory의 세 파일을 덮어쓴다.
Metadata의 executable path에는 사용자명이나 machine별 directory가 포함될 수
있다.

### 두 Runtime의 결과를 해석하는 방법

CPython과 PyPy 행이 모두 생성되었다면 다음 조건을 확인한 뒤 중앙값을
비교해야 한다.

1. 모든 반복과 interpreter의 checksum이 같은가?
2. 두 runtime의 iteration 및 repeat 수가 같은가?
3. Machine에서 큰 background workload가 실행되지 않았는가?
4. Runtime version과 executable path를 기록했는가?

현재 중앙값에는 초기 warm-up 반복도 포함된다. 정상 상태를 더 엄밀히
연구하려면 반복 수를 늘리고, 초기값을 임의로 버리기보다 사전에 정의한
post-warm-up 구간을 별도로 보고해야 한다.

### 한계와 타당성 위협

- 산술 microkernel 하나로 web application, data processing, scientific Python,
  객체 중심 application을 대표할 수 없다.
- 7회 반복은 현상을 관찰하기에는 유용하지만 강한 통계적 결론이나 신뢰구간을
  제시하기에는 부족하다.
- `warmup_ratio`의 분모인 최솟값은 우연히 빠른 sample 하나에 민감하다.
- Interpreter 실행 순서가 고정되어 있고 무작위화되지 않았다.
- CPU boost, thermal throttling, antivirus, scheduler와 background program이
  경과 시간에 영향을 줄 수 있다.
- Startup 시간은 의도적으로 제외했다. 따라서 실행 중 workload 분석에는
  적합하지만 startup 비중이 큰 CLI program을 설명하지는 못한다.
- 같은 runtime의 반복은 JIT와 process state를 공유하지만 서로 다른 runtime은
  별도 process이므로 state를 공유하지 않는다.
- C extension 중심 workload에서는 PyPy 호환성과 성능 특성이 다를 수 있다.
  이 benchmark는 standard library만 사용한다.
- Metadata에는 full runtime version, CPU model, power plan, 반복별 system state가
  기록되지 않는다.
- 현재 harness는 실행 주체를 CPython이라고 가정해 label을 지정한다.

### 결론

Experiment 21은 CPython과 PyPy에서 반복되는 순수 Python loop의 성능과 잠재적
JIT warm-up을 관찰하기 위한 작고 재현 가능한 harness다. 저장된 Windows 결과의
CPython 중앙값은 `0.2636634초`이고, 2026년 8월 9일 Linux 재실행에서는
`0.32231003초`였다. 두 환경 모두 PyPy가 설치되어 있지 않았으므로 핵심인
runtime 간 비교 질문은 아직 열려 있다.

### 향후 작업

- Metadata에 PyPy와 CPython의 정확한 version string 저장
- 발견한 implementation과 지정한 label의 일치 여부 검증
- 독립 trial마다 interpreter 실행 순서를 무작위화하거나 교대
- 설정 가능한 warm-up과 별도의 steady-state 구간 추가
- 여러 fresh process의 분산과 신뢰구간 보고
- 객체 allocation, 문자열 처리, branch-heavy workload 추가
- Startup을 포함한 latency를 별도 실험으로 비교
