# Historical baseline — 10 October 2026

## Decision

**No candidate passed the development gate.** All three strategies lost money at normal and doubled costs. Cash outperformed all three. No candidate was frozen or promoted, and the April–June 2026 holdout was not evaluated. This study does not justify more aggressive live trading.

## Scope

- Verified Kraken full OHLCVT archive through 30 June 2026; whole-archive SHA256 `fc81b54cba6e12af3e9422dde9416179e6ef76af4831d48d839fbdb43018eaa4`.
- Six preregistered EUR markets: BTC, ETH, SOL, DOGE, SHIB and PEPE. Original hourly/15-minute files and Kraken manifest are preserved under `research-data/` (ignored by Git).
- Development: 1 August 2025 inclusive to 1 April 2026 exclusive, 5,832 hourly bars. July provides warmup; each market needs 720 consecutive prior hours. Gaps restart warmup, never create synthetic candles or executions, and may leave stale position marks until trading resumes.
- Capital €500. Fees 0.8% per side; slippage 0.1% per side. Stress doubles both. These are current-cost scenarios, not reconstructed historical fee tiers.
- Planned risk 1% per trade, 20% position limit, five slots, 60% total exposure, 40% memecoin exposure, 4% stop, 10% target, 24-hour maximum hold and 10% drawdown halt. No account settings were changed.
- Automatic means the default controller in the protocol, not necessarily a user's promoted controller. Fast momentum is hourly, not a 15-minute strategy.

## Results

| Candidate | Net return | Doubled-cost return | Max drawdown | Closed trades | Net expectancy/trade | Profit factor | Fees |
|---|---:|---:|---:|---:|---:|---:|---:|
| Default automatic | -8.75% | -9.58% | -10.63% | 50 | -€0.88 | 0.37 | €45.28 |
| Hourly fast momentum | -10.09% | -10.12% | -10.09% | 47 | -€1.07 | 0.11 | €40.01 |
| Simple momentum | -8.75% | -10.34% | -10.29% | 66 | -€0.66 | 0.44 | €59.18 |

Normal-cost benchmarks: cash 0%, BTC holding -42.88%, equal-weight holding -53.57%. **Equal weight uses only assets with complete benchmark-period coverage, not necessarily all six.** Lower losses than buy-and-hold do not establish positive expectancy or superiority to cash.

Longest continuous time underwater: 5,534 / 5,738 / 5,743 hourly bars respectively. Drawdown can exceed the configured halt because gaps, costs and already-open exposure remain; the halt is not a guaranteed loss cap.

## Isolated exit comparison

All five policies were registered before the first comparison ran, using the same automatic controller, dates, costs and planned risk budget. Summary and full artifacts are preserved in `research-runs/exit-suite/`.

| Exit policy | Net return | Doubled-cost return |
|---|---:|---:|
| Fixed baseline | -8.75% | -9.58% |
| Two-ATR initial stop | -9.47% | -9.96% |
| Trailing after 4% favorable move | -9.52% | -10.88% |
| 24-hour maximum duration | -8.75% | -9.58% |
| Insufficient progress after 12 hours | -11.00% | -10.23% |

The time variant matches the baseline because the baseline already has a 24-hour maximum hold. None demonstrated positive net expectancy or grounds for live activation. These are isolated development comparisons, not a search for the best combination. The holdout was not consumed for any variant.

## Evidence and limitations

Registration: `research-runs/baseline/protocol.json`.

Protocol ID: `ee9b53beddd2924968390d413ad4cad703507c4172236bee71a02de2e94e086e`.

Research code identity: `c850a074d16358a3e0c261f482048947b0456b53273885f68549b05458e272ce`. Reproduction must use that recorded source version and the checksum-matching data.

Retained artifacts under `research-runs/baseline/`:

- `development-auto-20261010T091929746533.json`
- `development-fast-momentum-20261010T091955136643.json`
- `development-momentum-20261010T092022939782.json`

Artifacts contain cost stress, trades, equity curves, per-asset/month profit, concentration, uncertainty estimates, configuration/data fingerprints and limitations. The source protocol is also in `docs/research-baseline-protocol.json`.

Historical spreads, depth, partial fills, changing minimum orders, point-in-time universe selection and actual account fee tiers are not reconstructed. Exit liquidity is modeled. This is development research, not forward validation. Do not repeatedly tune against the reserved holdout.

## Aggressive settings: paper testing only

There is no demonstrated "best" aggressive setup here. A bounded paper hypothesis is:

- Maximum five positions, 20% each, 60% total exposure and 40% combined memecoin exposure.
- Planned risk 1% of equity per trade; 4% stop, 10% take-profit and 24-hour maximum hold. Sizing limits may reduce allocation; gaps can exceed planned losses.
- Enable 2% rolling-day and 5% rolling-week halts, plus 10% drawdown protection. These are hypotheses, not validated optimums or guarantees.
- Maximum spread 0.3%. Higher permits worse quotes and more opportunities; lower rejects more trades but limits bid/ask cost. Do not raise it just to remove waiting messages.
- Use the verified Kraken taker fee and realistic slippage, not an artificially low fee to generate signals. Account-specific fees can differ from old defaults: [Kraken fee schedule](https://www.kraken.com/features/fee-schedule).

This is not a recommendation to enable a losing strategy live. Hourly fast momentum can be tested separately, but it performed worse in this development window. None of these settings was applied to the live account.
