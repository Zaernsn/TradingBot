# Incremental shadow testing — 11 October 2026

Implemented the first major slice of the next-system plan: resume virtual forward portfolios from persisted checkpoints instead of replaying every prior trading decision at every update.

## Behavior

- Normal-cost, doubled-cost, and momentum-benchmark simulations have independent checkpoints in `ShadowRun.metrics`.
- Checkpoints retain cash, positions, entry fees, stop/high-water state, last exits, daily entry counts, rolling equity history, peak/halt state, trades, benchmark marks, timestamps and cumulative metrics.
- The existing replay loop remains the single transition implementation. Resume starts at the next unprocessed candle, preserving original step numbering, past-only signals, next-bar fills, gap warmup and stop-first ordering.
- Checkpoints use JSON-safe date/time encoding, a schema version, state checksum, frozen configuration/code identity, and hashes of all previously observed candles including warmup.
- Changed settings, code, processed candles, universe, or removed history invalidate the shadow run and reject the candidate. Existing virtual trade/equity evidence remains preserved rather than silently rewritten. A fresh evaluation is required.
- Checkpoints, new virtual trades, equity records and qualification decisions commit in the existing database transaction. Duplicate updates process zero new bars; ledger queries and writes target only newly generated records after a saved checkpoint.
- No new table or migration is required. Existing frozen-version rules still apply: approval from old source code is not silently reused after this source change.
- Promotion gates, account activation, pilot limits, orders, and protective exit paths remain unchanged. This release performs no deployment, account activation or exchange orders.

The first update for a compatible run establishes its checkpoint with a full replay. Later updates process only new decisions. Persistence is independent of application memory, so a process restart can reload the same state. This uses the existing serialized research-job scheduling; it does not add a distributed multi-worker locking protocol.

## Modes and visibility

`SHADOW_REPLAY_MODE` supports:

- `incremental` (default): validate and resume checkpoints.
- `compare`: resume, also perform full replay, and require identical result evidence before persisting the update. This verification mode intentionally costs more.
- `full`: perform full replay while still validating existing checkpoints before appending evidence. It cannot bypass revised-data rejection.

Per-scenario mode, elapsed time, new/total bar counts and comparison status are saved in run metrics and available as `shadow_replay` in the research-status API. Checkpoint contents are not exposed by that status field.

Checkpointing is restricted to the explicitly supported rule strategies with a declared universe and no terminal liquidation. Learned prediction models require a separate model/training-state persistence protocol and are rejected by this checkpoint API. Ordinary offline full replay remains available for them.

## Measured result

The repeatable benchmark uses a deterministic synthetic history of three markets and 720 bars per market, adding five bars per update. It runs three repetitions per scenario and checks complete result parity, including trades, equity, statistics, benchmark values and experiment identities. Duplicate updates process zero bars in every scenario.

| Timeframe | Scenario | Full replay median | Incremental median | Speed improvement |
|---|---|---:|---:|---:|
| Hourly | Normal | 0.555 s | 0.086 s | 6.48× |
| Hourly | Doubled costs | 0.648 s | 0.105 s | 6.17× |
| Hourly | Momentum benchmark | 0.549 s | 0.102 s | 5.39× |
| 15 minutes | Normal | 0.739 s | 0.107 s | 6.91× |
| 15 minutes | Doubled costs | 0.807 s | 0.106 s | 7.64× |
| 15 minutes | Momentum benchmark | 0.733 s | 0.127 s | 5.78× |

These are local replay measurements, not profitability results or a guarantee of production throughput. They include engine construction, integrity hashes, statistics and checkpoint serialization, but exclude database/network latency. Full runs process 690 hourly or 623 quarter-hour evaluation bars; incremental runs process five.

Historical input validation, checkpoint encoding, result aggregation/bootstrap statistics and saved history still grow with the observation window. This release reduces repeated per-bar strategy/risk work; it does not make the entire update constant-time. No historical candle collection or feature-cache redesign was included in this slice. A later optimization can normalize checkpoint storage and cache verified immutable input prefixes after measuring those costs.

Reproduce from `backend` with `python -m app.cli.benchmark_shadow --output ../docs/INCREMENTAL_SHADOW_BENCHMARK_2026_10_11.json`. The saved JSON records the current research code identity and all six timing/parity results.

## Verification and rollout

- Full backend suite: **301 passed**, including **19 incremental-replay cases**. Existing dependency deprecations and fixture warnings remain.
- Coverage includes all five Automatic families, hourly/15-minute portfolios, actual entries and open holdings, costs, gaps, restart via JSON/database reload, duplicate jobs, partial market coverage recovery, changed settings, removed/revised history, corrupt state, and full-mode invalidation safeguards.
- Database integration tests verify independent checkpoints, comparison-mode parity, preservation of rejected evidence, no duplicate virtual records, and zero exchange order records.
- No frontend implementation changed; frontend production checks were not repeated for this backend slice.

To roll out, rebuild/restart the backend with existing account activation and risk settings preserved. Optionally use `compare` initially to observe production-data parity before returning to `incremental`; compare mode is a verification aid, not a faster setting. Monitor invalidation reasons and replay timing. The deployed service was not restarted in this task.

The next research priority is timestamped execution-cost collection and loss attribution. Faster testing preserves the existing results; it does not turn the previously losing intraday candidates into approved strategies.
