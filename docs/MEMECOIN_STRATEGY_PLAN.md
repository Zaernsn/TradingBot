# Aggressive memecoin strategy improvement plan

Prepared 23 September 2026. Scope: the existing Kraken EUR spot bot. This is a research and implementation proposal, not a demonstrated profitable strategy. Values below are initial paper-test hypotheses. Repository defaults were inspected; saved account settings and actual trading performance were not inspected.

## Immediate rollout update

The user selected fast meme momentum with a saved 40% model threshold and no mandatory calendar waiting period. Implemented locally: selectable hourly fast momentum, meme-only entries, volatility-normalized ranking, one-hour cooldown, turnover and two-sided depth capacity limits, backtest strategy selection, and the updated small-account preset. The preset uses two EUR 20 positions, 25% per-coin and 50% aggregate ceilings, matching the pre-existing aggressive preset's capital allocation; this differs from the generic research allocation below. Model mode buys strictly above 40%, holds at 40%, and sells below 40% after qualification. Momentum ignores that probability setting.

The first implementation keeps fixed stops/profit targets and adds the existing 24-hour maximum-hold option to the preset. It does not yet implement the proposed 15-minute trigger, breadth gating, ATR sizing/exits, exchange-hosted protection or daily/weekly loss halts. Historical depth remains unavailable. Code availability is not evidence of profitability or confirmation of deployment. See README for account-specific activation instructions.

## Recommendation

Build a dedicated memecoin momentum strategy that concentrates on liquid leaders, enters on confirmed acceleration, and preserves winning trends with volatility-aware exits. Make aggression conditional on market breadth and measured execution quality. Begin with the current exposure ceiling; increase it only after the signal and execution improvements pass evaluation.

Stay with Kraken spot for this iteration. Newly launched DEX tokens require a separate execution stack, contract screening, wallet-concentration analysis and liquidity-withdrawal monitoring. They should not be treated as an extension of the current exchange watchlist.

## What the current code actually does

- `backend/app/services/bot_service.py` implements the selectable momentum strategy using `MomentumModel`: 24-hour momentum above the greater of 1% or modeled round-trip costs. Decisions use completed hourly candles. The model-based strategy is a separate selectable option; the default is `model`.
- `backend/app/ml/strategies.py` already contains a research-only `FastMomentumModel`: three-hour strength, six-hour closing-price breakout, price above a preceding 12-hour mean, and volume at least 1.2 times its preceding 24-hour mean. It is not the runtime momentum option.
- Discovery refreshes every five minutes and the watchlist supports 30 assets. Faster discovery does not imply faster entry signals.
- Risk defaults permit 5% equity per meme position, 10% aggregate meme exposure, a 0.3% spread and EUR 5,000 daily pair turnover. Older deployment/review documents describe different defaults; code and saved configuration must be reconciled before experiments.
- Optional planned-loss sizing exists but defaults to disabled. Entry allocation is also capped by equity divided by configured position slots. Twenty slots therefore impose a 5% allocation ceiling even if another cap is higher.
- Runtime entries iterate through watchlist order. The research `rank_entries` helper is not used by that entry loop. Ranking current qualified opportunities before allocating scarce capital is an explicit improvement.
- Research documentation identifies missing historical depth/partial-fill replay, incomplete historical universe reconstruction, and missing exchange-hosted stop lifecycle management. These limit conclusions from current backtests.

## 1. Trade liquid leaders

Retain a broad watchlist but buy only the highest-ranked qualifying opportunities. Start with the top three simultaneous meme positions, subject to the existing 10% group cap and 5% individual cap; neither number is a target to fill.

Paper-test a EUR 100,000 minimum daily EUR-pair turnover, with EUR 250,000 and EUR 1 million as predefined alternatives. Keep the 0.3% maximum spread initially. These thresholds are hypotheses: depth at the intended order size is more useful than daily volume alone.

Before entry, use fresh bid/ask and book depth to estimate the purchase and a stressed liquidation of the resulting position. Reject or reduce orders that cannot fit the execution-cost budget. As an initial participation bound, cap an order at 0.1% of daily pair turnover and 5% of displayed executable depth within the allowed price impact. Displayed depth can disappear; do not treat these limits as guaranteed liquidity.

Rank eligible signals using volatility-normalized momentum, relative strength versus the eligible meme basket, volume acceleration, and expected execution costs. Freeze one simple scoring rule before evaluation; do not optimize a large collection of weights. Record scores, rejected candidates and all binding allocation caps.

## 2. Separate market conditions from entry timing

Use completed hourly candles for the market-condition filter. An initial rule permits full paper allocation when at least 60% of eligible tracked memes are above their prior 24-hour mean and the basket's median three-hour return is positive. Halve the allocation budget at 40–60% breadth; suspend new entries below 40%. Require adequate fresh coverage, initially at least ten eligible markets and 80% valid observations, or suspend new entries.

Evaluate this filter as a separate experiment against an always-enabled baseline. BTC/SOL shocks and portfolio correlation should be recorded as additional diagnostics before adding more tunable gates.

First test the existing hourly fast-momentum challenger unchanged. Then test a separate 15-minute trigger:

1. Hourly market conditions qualify.
2. A completed 15-minute candle closes above the highest high of the preceding eight completed candles.
3. Its volume exceeds 1.5 times the median volume of the preceding 20 candles.
4. Its close is no more than one 15-minute ATR(14) above the breakout level; larger extensions are skipped.
5. Fresh executable prices still satisfy spread, impact, cash and portfolio constraints.

Enter only after the triggering candle closes. Compare this breakout rule with one separately registered pullback/retest variant; do not blend them after seeing holdout results. No averaging down or repeated intrabar chasing. Begin with a one-hour re-entry cooldown after an exit. Faster bars need ingestion, timestamp validation and matching replay support before runtime activation.

## 3. Size for loss and give winners room

Enable the existing loss-budget control for paper evaluation, starting at 0.25% of account equity per trade. Test 0.5% only as a later risk-stage change. All existing cash, slot, correlation, individual and aggregate caps remain binding.

For the proposed volatility-aware strategy, size notional as the minimum of those caps, liquidity capacity, and equity times risk budget divided by planned stop distance plus estimated round-trip friction. The existing implementation also uses horizon volatility; align sizing and exit definitions rather than silently replacing it.

Initial exit hypothesis:

- Stop distance: two 15-minute ATR(14), bounded between 3% and 8% of entry. Skip signals needing a wider invalidation level rather than forcing an artificially tight stop.
- After a two-risk-unit favorable move, activate a two-ATR trailing exit. Persist the high-water mark across restarts. Compare this against the current fixed profit target; do not assume trailing improves results.
- Exit if the position has not reached a one-risk-unit favorable move after four hours; hard maximum holding time of 24 hours. Test these separately from the entry change.
- Keep full-position exits initially. Partial profit-taking adds minimum-order, rounding and residual-position complexity and should be a later challenger.

A risk unit is the initial entry-to-stop price distance. An illustrative EUR 1,000 account with a 0.25% planned loss budget and 6% stop plus 1% friction yields about EUR 35.71 notional before other caps. Reject quantities below exchange minimums instead of enlarging them to force a trade. Stops and sizing do not bound actual losses during gaps or failed execution.

Add a 2% daily equity-loss halt and a 5% rolling seven-day equity-loss halt for new entries, using deposit/withdrawal-adjusted equity. These are proposed controls, not existing configuration fields. Continue protective exits while halted; require a recorded review before resuming. Preserve the existing peak-drawdown halt as an additional ceiling.

## 4. Make execution part of the strategy

Replace reliance on the default 0.26% fee assumption with verified account/pair fees, charging taker costs whenever the order consumes liquidity. Kraken fees vary by tier and pair. Track fee, spread, impact, latency, rejected orders and partial fills separately; avoid double-counting spread already included in executable prices.

Record decision-time quotes and compare them with actual fills. Reconcile partial fills and unresolved orders before sizing another entry. Use a capped marketable limit for entries and cancel stale unfilled quantities; do not assume a limit order guarantees execution. Protective exits need a separately tested policy for unfilled orders and rapidly worsening liquidity.

Prioritize independent position monitoring and persistent exchange-stop ownership before larger live allocations. Native stop orders require reconciliation when another exit closes a holding, otherwise an independent stop can remain active. Add alerts for stale prices, failed exits, monitoring delays and unresolved orders. Entry scans must not delay protection.

## 5. Validate changes in a controlled sequence

Use the existing research registration, development, freeze and untouched-holdout workflow. Compare strategies at matched exposure and cost assumptions, with both the existing model strategy and 24-hour momentum as baselines.

| Experiment | Change | Main question |
| --- | --- | --- |
| A | Correct fees, capture quotes/depth and reason codes | Are apparent returns still positive after execution costs? |
| B | Liquidity filters and ranked allocation | Does selection improve net returns and reduce execution losses? |
| C | Existing hourly FastMomentumModel | Does earlier confirmation outperform 24-hour momentum? |
| D | 15-minute trigger with hourly market filter | Does additional responsiveness pay for extra turnover? |
| E | Volatility sizing and trailing/time exits | Does the payoff distribution improve at matched risk? |
| F | Incremental exposure increases | Does the selected strategy retain its edge at larger size? |

Use point-in-time listings and category membership, including removed assets. Where historical membership, spread or depth is unavailable, label the result a limited-universe candle simulation. Collect forward snapshots rather than inventing past liquidity. Include declining and sideways periods, next-observation execution, missing data, gap-through stops, order minimums and partial fills. Do not infer 15-minute execution quality from hourly candles.

Report net expectancy per trade, profit factor, drawdown, downside tail loss, time in market, turnover, fill rate, slippage, and contribution by coin and regime. Bootstrap uncertainty in time blocks to account for correlated trades. Preserve all attempted variants to expose selection bias.

Proposed promotion gates, fixed before testing:

- No mandatory calendar waiting period. Assess forward evidence as it accumulates. The executable assessment requires at least 100 closed trades and positive uncertainty-adjusted results; inadequate evidence remains inconclusive.
- Positive untouched-holdout and forward net expectancy, with a positive lower block-bootstrap confidence bound; otherwise evidence remains inconclusive.
- Net profit factor at least 1.2 and maximum drawdown below 8% at the proposed allocation.
- Remain net positive when modeled variable execution costs are doubled; separately test gap and outage scenarios.
- Removing the single largest winning trade does not make aggregate net P&L negative. Review concentration by asset and regime as well.
- No unresolved order-state or protective-exit defects. Paper results alone do not establish actual exchange execution quality.

These gates are proposed decision rules, not statistical proof or a profitability promise. Existing stricter research go/no-go requirements also apply. Passing permits considering a separately authorized small live acceptance test, not automatic deployment.

## Delivery sequence

1. Reconcile code defaults, documentation and saved settings; export baseline performance and entry rejection reasons. Implement fee verification and execution-quality logging.
2. Add ranked allocation, stronger liquidity capacity checks and the hourly fast-momentum paper option. Reuse one strategy implementation in replay and runtime.
3. Add validated 15-minute data, market-condition gating, volatility exits and persistent cooldown/stop state. Test each change independently before combining.
4. Complete protection lifecycle and failure recovery; run frozen historical and forward evaluation.
5. Only after the gates pass, consider aggregate meme exposure stages of 10%, 15%, then 20%, retaining the 5% individual cap and increasing one variable at a time. Each stage needs new execution and drawdown evidence. Larger exposure is a research proposal, not a setting changed by this plan.

## Sources and interpretation

- [Kraken fee schedule](https://www.kraken.com/features/fee-schedule): use current account/pair terms; a repository fee default is not confirmation of the user's actual fee.
- [Kraken stop-loss orders](https://support.kraken.com/hc/articles/7699391647892-stop-loss-orders): stops trigger market orders and can exist independently of positions, which makes exit reconciliation necessary.
- [Kraken trailing-stop orders](https://support.kraken.com/articles/trailing-stop-orders): trailing triggers generate market orders; a trailing level is not a guaranteed fill price.
- [Chainalysis market manipulation research](https://www.chainalysis.com/blog/crypto-market-manipulation-wash-trading-pump-and-dump-2025/): documents suspected wash trading and pump-and-dump patterns. This supports scrutiny of raw volume; it does not establish the prevalence of manipulation in our Kraken universe.

Repository evidence: `backend/app/ml/strategies.py`, `backend/app/services/bot_service.py`, `backend/app/services/risk_service.py`, `backend/app/services/memecoin_service.py`, `backend/app/core/config.py`, and `docs/RESEARCH_WORKFLOW.md`.
