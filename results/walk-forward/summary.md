# Walk-forward (4h, 5 pairs, 160 grid combinations)

## Windows (test months only; means across pairs)

| fit | test | refit choice | fixed return % / Sharpe / >0 | refit return % / Sharpe / >0 | previous_defaults return % / Sharpe / >0 | buy & hold % |
|---|---|---|---|---|---|---|
| 2021-01..2022-12 | 2023-01..2023-06 | sl=3.5 trail=6 rr=5 rsi_max=100 | 1.20 / 0.31 / 3 | 1.28 / 0.67 / 4 | -1.81 / -1.70 / 1 | 54.7 |
| 2021-07..2023-06 | 2023-07..2023-12 | sl=4 trail=5 rr=20 rsi_max=100 | 4.30 / 1.09 / 5 | 3.01 / 0.96 / 5 | -1.16 / -1.16 / 0 | 114.8 |
| 2022-01..2023-12 | 2024-01..2024-06 | sl=4 trail=4 rr=5 rsi_max=100 | 1.42 / 0.36 / 3 | 1.13 / 0.22 / 3 | 0.55 / 0.29 / 4 | 41.5 |
| 2022-07..2024-06 | 2024-07..2024-12 | sl=4 trail=6 rr=5 rsi_max=100 | 2.28 / 0.13 / 3 | 0.74 / -0.09 / 2 | -1.26 / -0.82 / 2 | 85.3 |
| 2023-01..2024-12 | 2025-01..2025-06 | sl=3.5 trail=4 rr=20 rsi_max=100 | -0.11 / -0.64 / 1 | -0.85 / -0.98 / 1 | -0.97 / -1.48 / 0 | -6.2 |
| 2023-07..2025-06 | 2025-07..2025-12 | sl=4 trail=4 rr=20 rsi_max=100 | 2.50 / 0.80 / 4 | 1.66 / 0.83 / 4 | 0.23 / 0.07 / 2 | -0.7 |
| 2024-01..2025-12 | 2026-01..2026-06 | sl=3.5 trail=5 rr=20 rsi_max=100 | -1.78 / -1.38 / 1 | -1.73 / -1.49 / 1 | -1.68 / -2.64 / 0 | -40.4 |
| 2024-07..2026-06 | 2026-07..2026-08 | sl=3.5 trail=5 rr=20 rsi_max=100 | 1.80 / 0.72 / 2 | 2.11 / 0.63 / 2 | -0.03 / -0.17 / 2 | 36.1 |

## All test windows chained

| variant | mean return % | mean max DD % | worst max DD % | mean Sharpe | pairs > 0 |
|---|---|---|---|---|---|
| fixed | 11.79 | 7.65 | 11.64 | 0.60 | 4/5 |
| refit | 7.56 | 6.50 | 9.86 | 0.43 | 3/5 |
| previous_defaults | -5.99 | 6.64 | 11.39 | -0.77 | 0/5 |

## Test windows from 2024-07 chained

| variant | mean return % | mean max DD % | worst max DD % | mean Sharpe | pairs > 0 |
|---|---|---|---|---|---|
| fixed | 4.39 | 6.04 | 8.74 | 0.45 | 5/5 |
| refit | 1.77 | 5.32 | 7.41 | 0.19 | 3/5 |
| previous_defaults | -3.66 | 4.55 | 8.93 | -0.81 | 0/5 |

## Decision

- All windows: refit beat fixed in 2 of 8 windows; checks {'higher_sharpe': False, 'wins_majority': False, 'drawdown_ok': True}.
- Windows from 2024-07: refit beat fixed in 1 of 5 windows; checks {'higher_sharpe': False, 'wins_majority': False, 'drawdown_ok': True}.

Adopt refit: **False**. Latest window's choice: sl=3.5 trail=5 rr=20 rsi_max=100.
