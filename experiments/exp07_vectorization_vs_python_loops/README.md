# Experiment 07 — Vectorization vs Python Loops

![Python loop and NumPy vectorization results](figures/vectorization.png)

## 1. Experiment Overview

동일한 원소별 수식 `y = x*x + 3*x`를 순수 Python 반복문과 NumPy 벡터화로 계산한다. 입력 생성 시간을 제외하고 계산 커널만 측정해, CPython의 원소별 반복·객체 연산 비용과 NumPy 배열 연산의 차이를 검증한다.

## 2. Research Question

100만 개의 `float64` 값을 처리할 때 NumPy 벡터화는 Python 반복문보다 얼마나 빠르며, 각 방식의 계산 중 추적 가능한 peak 메모리 할당량은 어떻게 다른가?

## 3. Background

Python 반복문은 원소마다 바이트코드를 실행하고 Python 객체에 대한 연산과 결과 저장을 수행한다. NumPy 벡터화는 연속된 동질 자료를 컴파일된 배열 루프에서 처리하므로 이 인터프리터 오버헤드를 줄일 수 있다. 다만 `values * values + 3.0 * values` 같은 표현식은 중간 배열을 만들 수 있으므로 속도 향상이 메모리 할당 제거를 뜻하지는 않는다.

## 4. Hypothesis

NumPy 벡터화가 Python 반복문보다 빠를 것으로 예상한다. NumPy는 컴파일된 내부 루프에서 연속 메모리를 처리하지만 Python은 원소마다 동적 객체 연산을 수행하기 때문이다. 메모리는 Python 결과 리스트와 개별 `float` 객체 때문에 Python 방식의 추적 peak가 더 클 것으로 예상하지만, NumPy 표현식의 임시 배열도 상당한 메모리를 사용할 수 있다.

## 5. Experimental Setup

- 기준 환경: CPython 3.13.5, NumPy 2.4.6, 64-bit Windows 11
- 입력: 0.0부터 1.0까지 균등한 값 1,000,000개
- Python 조건: `list[float]`
- NumPy 조건: C-contiguous `float64` ndarray
- 계산식: `y = x*x + 3*x`
- 타이머: `time.perf_counter()`
- 워밍업 2회, 조건별 측정 11회
- seed `20260718`로 매 반복의 조건 순서 무작위화
- 입력 생성과 정확성 검사는 측정 구간에서 제외
- 시간 측정 중에만 garbage collection 비활성화
- CPU 모델은 결과 해석에 유용하지만 실험 실행의 필수 입력은 아니다

실행 방법:

```bash
uv run python experiments/exp07_vectorization_vs_python_loops/benchmark.py
uv run python experiments/exp07_vectorization_vs_python_loops/benchmark.py --quick
```

## 6. Variables

- Independent variable: 계산 방법(`python_loop`, `numpy_vectorized`)
- Dependent variables: 실행 시간, 처리량, Python 기준 speedup, peak traced memory
- Controlled variables: 원소 수, 논리적 입력값, 수식, `float64` 정밀도, 프로세스, 타이머, 워밍업·반복 횟수, random seed

두 입력 컨테이너의 표현 방식은 각 구현에 필수적으로 결합된 차이이다. 따라서 결과는 반복문 문법 하나만이 아니라 Python 객체 리스트와 NumPy ndarray를 사용하는 실제 두 접근법 전체의 비교다.

## 7. Benchmark Methodology

`make_inputs()`가 동등한 리스트와 ndarray를 미리 만든다. `validate_results()`는 `np.allclose`로 두 구현의 결과를 측정 전에 확인한다. `benchmark_methods()`는 워밍업 후 각 반복에서 실행 순서를 섞고 함수 호출 전체를 측정한다. 결과 배열 생성은 실제 계산 비용이므로 포함하지만 입력 생성은 제외한다.

중앙값을 대표값으로 사용하고 평균, 표본 표준편차, 최솟값, 최댓값과 처리량도 저장한다. Speedup은 `Python loop 중앙값 / 해당 방식 중앙값`이다. 메모리 프로파일링 오버헤드가 시간 결과를 오염시키지 않도록 `measure_peak_memory()`를 별도로 한 번 실행하며, 각 커널 시작 시점 대비 `tracemalloc` peak 증가량을 기록한다.

## 8. Implementation Plan

1. 동일한 입력과 Python·NumPy 계산 함수를 구현한다.
2. 결과의 수치적 동등성을 검사한다.
3. 워밍업과 무작위 실행 순서를 적용해 시간을 반복 측정한다.
4. 메모리를 시간 측정과 분리해 측정한다.
5. 중앙값, 처리량, speedup과 peak allocation을 계산한다.
6. raw CSV, summary CSV, 환경 metadata와 그래프를 생성한다.
7. 작은 입력에 대한 정확성·통계 테스트와 정적 검사를 실행한다.

핵심 함수는 `python_loop()`, `numpy_vectorized()`, `benchmark_methods()`, `measure_peak_memory()`, `summarize()`이며 별도 클래스는 필요하지 않다.

## 9. Measurements

- `results/raw.csv`: 반복별 method, 실행 순서와 실행 시간
- `results/summary.csv`: 시간 통계, 처리량, speedup, peak traced bytes
- `results/metadata.json`: Python·NumPy·OS 버전과 실행 설정
- `figures/vectorization.png`: 중앙 실행 시간, speedup, peak traced memory

## 10. Visualization

그래프의 x축은 계산 방법이다. 첫 그래프의 y축은 중앙 실행 시간(ms), 두 번째는 Python loop 기준 speedup, 세 번째는 계산 중 peak traced memory(MiB)다. 따라서 시간 차이와 그 과정에서 발생한 추적 가능 할당량을 함께 비교할 수 있다.

## 11. Expected Results

NumPy 벡터화의 중앙 실행 시간이 더 짧고 처리량과 speedup이 높을 것으로 예상한다. 차이가 작거나 역전된다면 입력이 너무 작아 호출·배열 할당 비용이 지배적이거나, 시스템 부하·CPU 주파수·메모리 상태의 영향일 수 있다. 다른 수식에서는 NumPy 임시 배열의 수와 내부 커널 특성 때문에 speedup과 메모리 결과가 달라질 수 있다.

## 12. Threats to Validity

한 대의 컴퓨터, 한 가지 크기·dtype·수식만 측정했다. Python과 NumPy가 사용하는 컨테이너와 내부 숫자 표현이 다르므로 반복 실행 메커니즘만 격리한 미시 실험은 아니다. OS scheduling, CPU frequency, 발열, background load와 cache state는 완전히 통제하지 못했다.

`tracemalloc` 값은 커널 실행 중 Python allocator와 NumPy가 노출한 추적 가능 할당의 peak이며 프로세스 전체 RSS나 모든 native allocation을 뜻하지 않는다. 메모리 측정은 1회이므로 시간 통계와 같은 분포를 제공하지 않는다. 또한 NumPy 표현식은 임시 배열을 만들며, in-place 연산이나 식 융합 라이브러리는 다른 결과를 낼 수 있다.

## 13. Experiment README

### Overview

Python 반복문과 NumPy 벡터화로 같은 100만 원소 수식을 계산해 실행 시간, speedup과 메모리 할당을 비교했다.

### Background

벡터화는 원소별 Python 바이트코드와 객체 연산을 컴파일된 배열 루프로 옮긴다. 이로써 인터프리터 오버헤드를 줄일 수 있지만 중간 ndarray 할당 비용은 남는다.

### Research Question

NumPy 벡터화는 Python 반복문보다 얼마나 빠르며 계산 중 추적되는 peak 메모리는 어떻게 다른가?

### Hypothesis

NumPy가 더 빠르고, 개별 Python `float` 결과를 만드는 반복문보다 낮은 peak traced allocation을 보일 것으로 예상했다.

### Experimental Setup

`float64` 값 1,000,000개에 `y = x*x + 3*x`를 적용했다. 입력 생성은 제외했으며 2회 워밍업 후 조건별 11회를 무작위 순서로 측정했다. 메모리는 시간 측정과 분리해 `tracemalloc`으로 기록했다.

### Results

2026-07-18 KST 기준 실행 결과이며 시간은 11회 측정의 중앙값이다.

| Method | Median time | Throughput | Speedup | Peak traced memory |
| --- | ---: | ---: | ---: | ---: |
| Python loop | 74.760 ms | 13.38 M elem/s | 1.00× | 30.52 MiB |
| NumPy vectorized | 13.986 ms | 71.50 M elem/s | 5.35× | 22.89 MiB |

### Discussion

이 환경에서 NumPy 벡터화는 Python 반복문보다 5.35배 빨랐고 처리량은 약 5.35배 높았다. 결과는 벡터화가 원소별 인터프리터·객체 연산 비용을 줄인다는 가설과 일치한다. Python loop의 peak traced allocation은 NumPy보다 약 7.63 MiB 컸다. 다만 NumPy도 수식의 중간 배열 때문에 최종 결과 ndarray 크기(약 7.63 MiB)보다 큰 22.89 MiB를 할당했다.

표준편차는 Python 10.23 ms, NumPy 4.14 ms였고 각 측정 범위는 각각 59.65–95.81 ms, 7.03–18.83 ms였다. 따라서 단일 실행값보다 중앙값을 사용하는 것이 중요하며, 5.35배라는 비율은 이 기준 환경과 수식에 한정된다.

### Conclusion

100만 원소의 이 원소별 계산에서는 NumPy 벡터화가 더 빠르고 추적된 peak allocation도 더 작았다. 벡터화의 장점은 간결한 문법 자체보다 컴파일된 배열 루프에서 대량의 동질 데이터를 처리하는 데서 나온다.

### Future Work

여러 원소 수에서 crossover 지점을 측정하고, 더 복잡한 수식과 in-place NumPy 구현을 비교하면 배열 할당 비용과 계산량이 speedup에 미치는 영향을 구분할 수 있다. 이는 현재 결과를 확장하는 후속 작업이며 이 실험에는 포함하지 않았다.

## 14. Suggested Commit Message

`feat: add Experiment 07 vectorization benchmark`

## 15. Suggested Folder Structure

```text
experiments/exp07_vectorization_vs_python_loops/
├── README.md
├── benchmark.py
├── figures/
│   └── vectorization.png
└── results/
    ├── metadata.json
    ├── raw.csv
    └── summary.csv
```
