# Faster Automatic research — 11 October 2026

The subsequent [intraday upgrade](INTRADAY_STRATEGY_UPGRADE_2026_10_11.md) adds
completed-15-minute candidates and supersedes this document's hourly-only scope.

Implemented locally at the user's request to remove the fixed seven-day wait,
reconsider entries more frequently and strengthen automatic strategy selection.
This supersedes earlier release descriptions of the seven-day gate and 25% pilot.

## Implemented behavior

- No minimum forward days. Historical qualification is still mandatory; forward
  qualification still requires 30 closed shadow trades, positive net return and
  expectancy, positive doubled-cost results, performance above momentum, drawdown
  within 5% and top-five profit share no greater than 80%. Missing profit-share
  evidence blocks qualification. The 30-day maximum remains an expiration for
  unsuccessful shadow tests, not a minimum wait.
- Historical development failures stop after one simulation. Validation failures
  stop before final-test, stress or benchmark simulation. Unevaluated stages are
  stored as null and explicitly shown as skipped, not artificial zero returns.
- Before final tests, two separately simulated chronological validation windows
  must each have positive expectancy and at least five closed trades. These are
  time-window robustness checks, not proof of coverage across market regimes.
- Research runs every five minutes, at most three candidate evaluations per
  account and no overlapping research jobs. Computation remains in a background
  thread. Each batch reads one candle snapshot; identical benchmark simulations
  reuse results within that batch. Cache keys distinguish costs, capital, dates,
  terminal-liquidation policy and the exact snapshot object.
- Automatic signals are reevaluated each nominal 30-second entry cycle using
  completed hourly evidence. Improved execution conditions can permit entry on
  an unchanged qualified BUY. Unchanged signals reuse their ledger row. The bot
  still prevents adding to held positions, respects retry backoff, and requires
  new completed evidence before reentering an asset sold after that evidence.
- The first live pilot is capped at one position and 5% aggregate exposure;
  stricter saved account limits apply. Existing exposure consumes the budget.
  A realized loss of 1% of pilot starting equity suspends new entries. Stops,
  protective monitoring and exits remain available; suspension does not itself
  liquidate positions. Gaps and execution costs can exceed the loss threshold.
- Existing live promotion requires ten exits with positive aggregate P&L, not
  ten individually profitable trades. Existing reconciliation, unresolved-order,
  cost and risk-halt checks remain mandatory.
- Strategy Lab shows the new policy, early rejection stage, window results and
  evidence progress without a seven-day countdown.

No schema migration is needed. No account mode, running flag, credentials, saved
risk limits or historical strategy results were changed. These changes have not
been deployed to a running trading service or used to place an exchange order.
Rebuild/restart the backend and frontend to use them. Source identity freezing
remains enforced: forward evidence from a different code/risk version must not
be silently reused as new-version qualification.

## Next development priorities

1. Build and independently validate a completed-15-minute challenger. Generalize
   replay intervals, warmup, embargoes, signal horizons and annualization together;
   use genuine 15-minute history and realistic spread, turnover and fee scenarios.
   Faster reevaluation of hourly evidence is not a faster-timeframe strategy.
2. Add market-regime reports and multiple chronological development windows;
   reserve final evidence before testing variants. Include listing dates and
   point-in-time universe selection, not only today's surviving markets.
3. Make shadow processing incremental, preserving cash, positions, cooldowns,
   rolling loss state and stress/benchmark state. Verify restart parity against
   complete replay before enabling it.
4. Attribute live evidence to a controller's own completed round trips, including
   partial fills, so preexisting holdings cannot provide misleading pilot proof.
   Add gradual capital stages supported by that evidence.
5. Replay recorded quote/depth data and compare actual fills with predictions.
   Promote on uncertainty-aware evidence with dependence and repeated testing
   accounted for, rather than treating trade counts as statistical proof.

The saved historical baseline still lost money after fees. No new performance
study in this release demonstrates profitability, and no automatic winner is
forced when candidates fail.

## Verification

- Full backend regression suite: 261 passed. Existing dependency deprecations
  and a SQLAlchemy test-fixture warning remain.
- Frontend production build, Strategy Lab rendering, tracked-market calculations
  and UI helper checks passed.
- Regression cases cover sub-day qualification with enough forward trades,
  insufficient trades, concentrated/missing profit evidence, early stage rejection,
  validation-window failure, cache isolation, pilot loss suspension, same-candle
  liquidity recovery, retry backoff, duplicate-entry prevention and new evidence
  after an exit.
- No historical holdout, account configuration or real exchange execution was
  used to claim performance improvement. No new schema migration is required.
