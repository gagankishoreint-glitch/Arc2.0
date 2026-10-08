# ARC Experiment Results

Machine: 2 logical CPUs, 2.1 GB RAM, platform=linux, elevated=True

## E1 Trigger->enforcement latency

| sampling interval | mean (ms) | stdev (ms) | min | max |
|---|---|---|---|---|
| 0.2s|debounce=0.0s | 202.1 | 0.3 | 201.6 | 202.6 |
| 0.2s|debounce=0.2s | 402.6 | 0.8 | 402.0 | 404.8 |
| 0.5s|debounce=0.0s | 503.2 | 0.6 | 502.6 | 504.4 |
| 0.5s|debounce=0.2s | 1004.0 | 0.6 | 1003.1 | 1004.9 |
| 1.0s|debounce=0.0s | 1007.2 | 6.1 | 1004.9 | 1024.5 |
| 1.0s|debounce=0.2s | 2009.3 | 3.6 | 2006.3 | 2016.6 |

## E2 Engine overhead (20 background processes)

| sampling interval | CPU % (mean) | CPU % (max) | RSS (MB) |
|---|---|---|---|
| 0.5s | 2.56 | 3.0 | 18.6 |
| 1.0s | 1.44 | 2.0 | 18.6 |
| 2.0s | 0.75 | 1.5 | 18.6 |

## E3 Restoration correctness

- Exact restores: **40/40 (100.0%)** (nice + affinity)

## E4 Enforcement efficacy (worker CPU share under contention)

| configuration | worker CPU share (% of one core) |
|---|---|
| all-nice-0 | 67.1 |
| worker--5-hogs-0 | 99.6 |
| worker-0-hogs-19 | 99.6 |
| worker-19-hogs-0 | 13.9 |

## E5 Live contract lifecycle

- trigger -> first action: **304.3 ms**
- restoration events: 1
- background nice 10 -> restored 10 (exact: True)

## E6 Memory-pressure contract

- memory 25.4% -> peak 70.0%
- contract triggered: True, hog nice during enforcement: 10, - restored after pressure cleared: True
