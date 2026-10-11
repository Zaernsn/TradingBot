# Automatic 15-minute strategy upgrade — 11 October 2026

Automatic can now research and select a completed-15-minute breakout strategy,
in addition to its existing hourly strategy families. A shorter candle interval
does not grant live approval: historical and genuinely forward evidence remain
required. No seven-day minimum has been reintroduced.

## Strategy and lifecycle

- Three declared variants: 12/24/48-bar breakout lookbacks (3/6/12 hours),
  strength thresholds of 0.75%/1%/1.5%, and volume ratios of 1.25/1.5/2.
- All variants use completed quarter-hour prices, 24-hour basket breadth and
  three-hour strength. Defensive or insufficient market coverage blocks entries.
- A BUY requires closing-price breakout, rising trend, positive last-bar return
  no larger than 4%, volume confirmation, and three-hour strength above both the
  declared threshold and 1.5 times modeled round-trip costs. A short-term trend
  reversal can signal SELL. Quotes, liquidity, order minimums and risk checks
  remain independent final execution gates.
- At least 97 contiguous prior quarter-hour bars are needed for the strategy.
  Automatic research requires at least three markets with 720 saved bars and
  still applies development, two validation-window checks, embargoes, final-test,
  benchmark and doubled-cost gates. Passing history starts a virtual shadow run;
  no historical result directly opens a live position.
- Live qualification still requires 30 closed forward trades and passing net,
  stress, benchmark, drawdown and profit-concentration checks. The first live
  pilot remains limited to one position and 5% aggregate exposure. Existing live
  account activation, reconciliation and order controls remain required.
- The first eligible forward bar starts at the next boundary after the candidate
  was tested. Historical candles from before the test cannot become forward proof.
- Candidate identities include `timeframe=15m`. Old hourly identities and metadata
  stay compatible. Exports cannot authorize imported strategies.

## Data, replay and execution

The five-minute research job collects public Kraken quarter-hour history for
Automatic watchlists, with core-market fallback when no watchlist exists. It uses
an exchange without private account credentials and never submits an order.
Requests are limited to two concurrent fetches and skipped when the latest closed
bar is already saved. Data collection also runs for stopped Automatic accounts;
it does not start their trading bot.

The selected controller determines whether runtime histories use 1h or 15m bars.
For a 15m controller, a candle from 12:15 to 12:30 can first contribute at 12:30;
the nominal 30-second entry cycle then reevaluates it and current execution gates.
Repeated unchanged signals reuse their signal ledger row. A sold asset needs new
completed evidence before reentry. Protective position checks remain independent
of candle completion.

Replay now uses the declared bar duration for next-bar execution, intrabar and
terminal timestamps, daily aggregation, liquidity turnover, rolling daily/weekly
loss windows, annualization, and block-bootstrap duration. A full day is 96 real
quarter-hour bars, not 24. The ordinary momentum benchmark retains a 24-hour
lookback. Volatility-sizing horizons and correlation histories retain their
hour-based duration. Holding-time limits continue to use wall-clock hours.

Missing market bars remain missing. Explicit no-trade-gap replay restarts signal
warmup and never invents candles or executes without a real price. Historical
spread/depth, partial fills, changing minimum orders, category membership and
actual account fee tiers remain limitations. Generic hourly prediction models
are not silently reinterpreted as 15-minute strategies.

The initial candidate pool is now 24 baselines plus at most eight derived
variants. Up to 12 later bounded generations retain the existing new-evidence
rules, giving a maximum budget of 128 identities. Each family receives a first
mutation slot before remaining slots are used. Missing quarter-hour evidence
does not block available hourly baseline evaluations.

## Local rollout

No schema migration is needed: the candle table already keys records by symbol,
timeframe and timestamp, and candidate definitions are stored as JSON. No saved
account risk setting, mode, credential or running flag was changed. No real order
was submitted. The running service still requires a rebuild/restart to use these
changes; collecting history or completing an offline study does not deploy them.

Strategy Lab now identifies each candidate's hourly or 15-minute evidence and
shows the fifth family. No winner is forced and no historical loss is relabeled
as an approved strategy.

## Development study

Three protocols were registered before evaluating any variant. The study uses
the verified local Kraken quarter-hour source for BTC, ETH, SOL, DOGE, SHIB and
PEPE EUR markets. Development is 1 August 2025 through 31 March 2026, with July
available for warmup. April–June 2026 stays reserved and is not evaluated here.

Capital is EUR 500; modeled fees are 0.8% per side and slippage 0.1% per side,
with both doubled for stress. These are declared cost scenarios, not a claim of
matching a particular account's fee tier. Risk limits match the earlier baseline
protocol. Warmup is 97 quarter-hour bars, so gap recovery differs from the older
hourly study's 720-hour warmup; results do not isolate candle frequency alone.

Protocol inputs are preserved in `docs/intraday-protocol-{short,medium,long}-20261011.json`.
Registered protocols, source hashes, complete trades and equity curves are kept
under `research-runs/intraday-{short,medium,long}-20261011/`. The selected source
window is under `research-data/intraday-window-20261011/`. Those evidence folders
remain ignored by Git, as before. Compact results are also preserved in
`docs/INTRADAY_DEVELOPMENT_RESULTS_2026_10_11.json`.

| Variant | Net return | Doubled-cost return | Closed trades | Net expectancy per trade | Fees | Maximum drawdown |
|---|---:|---:|---:|---:|---:|---:|
| Short: 3-hour breakout | -9.91% | -9.88% | 44 | -EUR 1.13 | EUR 43.53 | -10.17% |
| Medium: 6-hour breakout | -10.00% | -8.59% | 55 | -EUR 0.91 | EUR 50.33 | -10.22% |
| Long: 12-hour breakout | -10.25% | -8.56% | 53 | -EUR 0.97 | EUR 51.57 | -10.48% |

**Decision: all three failed development qualification.** None was frozen,
promoted, or evaluated on the reserved April–June final-test period. Cash returned
0%; the 24-hour momentum replay on the same quarter-hour data returned -8.45%.
The complete artifacts retain source/code identities, costs, trades and
limitations. Research code identity for all three protocols:
`edb8a5707ea2aed5861ca14429fca1c9722ce89a413334bfc2cba83052152173`.

Doubled-cost runs can lose less because cost-aware gates, sizing and drawdown
halts change the trades taken; they do not replay an identical set of fills at
higher fees. Every doubled-cost variant still had negative expectancy. A 10%
drawdown halt is not a guaranteed 10% loss cap: already-open exposure, price gaps
and execution costs remain. Current results support continued research, not
activation of these variants with real money.

## Verification

- Full backend suite: **282 passed**, including 21 intraday-specific regression
  cases. Existing dependency deprecations and a SQLAlchemy fixture warning remain.
- Frontend production build and Strategy Lab, tracked-market and UI helper
  rendering checks passed.
- Checks cover completed-bar boundaries; three-hour/24-hour regime duration;
  bounded identities and mutations; cost/volume confirmation; next-bar execution;
  stop-first ordering; 96-bar daily aggregation; loss-window and annualization
  scaling; gap preservation; idempotent collection and request caching; separate
  research datasets; quarter-hour forward starts; actual paper BUY execution,
  no duplicate entries; and single-use final-test protection.
- No live account activation, running-service deployment, real exchange fill,
  or profitable new strategy is claimed by these checks.
