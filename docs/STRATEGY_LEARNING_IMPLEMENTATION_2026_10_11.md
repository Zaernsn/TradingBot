# Bounded strategy learning — 11 October 2026

**Policy update:** The user subsequently requested automatic live promotion.
See [Automatic strategy release](AUTOMATIC_STRATEGY_RELEASE_2026_10_11.md) for the
current policy, follow-up generations and updated dashboard. The manual-approval
description below records the earlier implementation, not current behavior.

Implemented on top of the existing hourly research worker for accounts using
the Automatic entry strategy. No account settings or running flags are changed.
This is a bounded parameter search, not arbitrary self-written trading code or
a promise of profitable improvement.

## Selection loop

- Evaluate the 21 declared candidates across four strategy families.
- Wait for the complete parent pool, then derive up to eight variations using
  development results only. Keep each parent's original development score frozen.
- Limit each account to 29 evaluated identities, including legacy identities.
- Require positive development, validation and final-test expectancy; final-test
  return above cash and momentum; positive doubled-cost results; at least 30
  closed final-test trades; drawdown no worse than 8%; profit concentration <=80%.
- Mark failures REJECTED, excluding them from approved selection. Preserve their
  scores and failed checks, rather than deleting them.
- Retest historical rejections only after 336 new hourly observations of elapsed
  history, using a final-test interval strictly after the previous test's end.
  Maximum 12 refreshes; retain all revisions within this budget. Missing bars are
  not fabricated and existing backtest data-integrity checks still apply.
- Never retest an identity with a shadow ledger: preserve its trades and equity
  history, including failed or invalidated runs.
- Successful new research candidates enter forward paper simulation. Freeze the
  strategy/code/risk identity from the historical test, including before the first
  forward pass. A changed identity invalidates the candidate.
- Even successful forward candidates remain PAPER_APPROVED, with an explicit
  awaiting_manual_live_approval marker. This release does not add a live approval
  button or grant permission to trade new candidates. Existing legacy live
  controllers and their safeguards are unchanged.

The dashboard shows rejected, paper-testing and ready-for-review counts. The
research API includes validation, final-test, stress results and policy limits.
The worker runs hourly (first pass five minutes after startup), at most three
historical evaluations per account per pass, off the main event loop.

## Boundaries

The original 2026-10-10 offline protocols/results remain historical artifacts;
source changes require a newly registered protocol for a new offline experiment.
No historical holdout is consumed by this implementation task. Unit/integration
tests verify behavior, not profitability. The previous negative baseline is not
reclassified as a winner. Shared historical tests across multiple candidates are
not independent statistical confirmation; genuinely forward paper evidence is
still essential. Parameter learning never modifies account risk limits.

For aggressive trading, there is no demonstrated best setting yet. Use paper
testing to explore frequency; do not widen spread limits or lower modeled fees
just to force more trades. A lower spread limit is stricter and usually permits
fewer entries; a higher limit accepts more expensive quotes.

## Verification and local deployment

- Learning regression tests: 21 passed after the final safety changes.
- Full backend suite: 250 passed, one failed because a pre-existing local edit
  spells the liquidity message `maxximum` instead of the expected `maximum`.
  That unrelated edit was preserved, not silently reverted.
- Frontend type checking, production build and tracked-coin tests passed.
- Database backup: `backups/pre-learning-20261011.dump`; archive listing verified.
- Docker Compose rebuilt and recreated backend/frontend successfully. Persistent
  database storage was kept. API health returned `ok`; frontend returned HTTP 200.
- All five running bot records reported HEALTHY protection after restart.
- Existing research ledger: 29 REJECTED, no approved winner. These are existing
  results, not a claim that this task ran 29 fresh historical experiments.
