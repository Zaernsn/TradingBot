# Execution-cost collection and loss attribution

Date: 11 October 2026
Status: implemented locally; not deployed and no real order submitted.

## What changed

Automatic research now collects public Kraken ticker and order-book snapshots alongside completed 15-minute history. It uses the public PaperExchange adapter without account credentials. A failed history fetch does not prevent quote collection or change an account's running flag.

Collection runs on the existing five-minute research schedule, including for stopped Automatic accounts. Each pass selects at most 30 distinct markets, rotating through larger combined watchlists. Two markets are fetched concurrently, with ticker/book requests bounded by ten-second timeouts and a thirty-second overall quote-collection deadline. One observation per exchange/market/five-minute bucket prevents duplicate archive records. Observations older than 14 days are pruned during collection.

The new `market_observations` table stores local request/receipt times, available source timestamps, quote spread, up to 20 bid/ask levels, bounded-depth EUR notionals and indicative EUR 25/100/500 liquidity probes. It preserves failed, partial, stale and invalid-time observations with sanitized failure types. It never stores authenticated exchange responses or credentials.

An observation becomes available at its actual receipt time, not its bucket or source timestamp. The past-only lookup requires receipt before the decision, fresh source timestamps, and valid evidence. It never uses a later snapshot to fill a historical evidence gap. Missing book timestamps remain partial evidence; adapter ticker timestamps can use a local fallback, which is explicitly documented.

## Cost accounting and interface

- Replay results now contain closed-trade fee/slippage attribution, net P&L, holding duration and breakdowns by asset, month and recorded exit reason. Missing historical reasons/regimes remain unavailable; they are not inferred.
- FIFO matching supports partial closes, allocates entry fees proportionally, and checks recorded closed P&L and total fees against the fill ledger. Open marked holdings are reported separately with an equity-reconciliation residual.
- Modeled slippage is derived only from the declared replay assumption. Historical spread/depth is not fabricated. Price P&L before modeled costs describes the identical recorded quantities and fill path; it is not a claim about how a zero-cost strategy would behave.
- Existing live order evidence is reused to measure fills against their own fresh decision quotes. Paper fills and stale/missing decision quotes are excluded from that comparison. Base-currency fees remain in their original currency instead of being given a fabricated EUR conversion.
- The authenticated `GET /api/v1/bot/research/execution-costs` endpoint returns public watched-market summaries and the current user's live-order cost evidence, limited to 500 orders from the last 30 days. Missing live evidence is null, not zero cost.
- Strategy Lab displays recorded spread, bounded depth, sample age and quality, actual live quote fees, matched-fill coverage, and each candidate's available modeled cost breakdown. A failure to load costs does not prevent loading the strategy evidence.

These observations do not alter entry eligibility, position sizing, promotion rules or order execution. Replaying quote/depth snapshots as executable historical liquidity is a later implementation slice.

## Diagnosis of the saved development studies

The report reads the existing frozen development artifacts; it does not rerun a strategy or consume the reserved final-test period. The study modeled fees of 0.8% per side and slippage of 0.1% per side. These are study assumptions, not a claim about any account's verified fee tier.

| Variant | Closed net P&L | Fees | Modeled slippage | Same-fill price P&L before modeled costs | Average hold |
|---|---:|---:|---:|---:|---:|
| Short | -EUR 49.57 | EUR 43.53 | EUR 5.44 | -EUR 0.59 | 5.01 h |
| Medium | -EUR 49.98 | EUR 50.33 | EUR 6.29 | EUR 6.64 | 5.07 h |
| Long | -EUR 51.26 | EUR 51.57 | EUR 6.45 | EUR 6.76 | 4.76 h |

All three equity reconciliations have residuals below EUR 0.0000001. DOGE accounts for roughly EUR 22–24 of each variant's loss, followed by SOL at roughly EUR 14–17. This is development-period attribution, not evidence that excluding either asset would improve unseen performance.

The medium/long variants' small price gains are overwhelmed by costs, while the short variant also loses before modeled costs on the same fills. This supports registering experiments around selectivity, turnover and stronger sustained moves. It does not justify lowering declared costs, removing qualification gates, or promoting any failed variant. Actual quote/depth evidence will help establish which future opportunities are executable.

The full diagnostic report, including doubled-cost and momentum-baseline scenarios, is saved in `INTRADAY_COST_ATTRIBUTION_2026_10_11.json`. Each artifact's digest and source path are retained. Reproduce one report from `backend` with `python -m app.cli.cost_attribution <development-artifact.json> --output <report.json>`.

## Deployment and limitations

Validation: **319 backend tests passed**, including 18 new collection/cost cases, the complete migration chain, legacy startup/restart preservation, and existing incremental-replay parity checks. Frontend production build and execution-cost, Strategy Lab, UI helper and tracked-market rendering checks passed. Existing dependency/fixture warnings remain. Migration discovery reports one head, `p61011market`.

Migration `p61011market` follows `p61010guards` and adds only the public observation archive. Rebuild/restart with migrations applied before using the collector. This task did not migrate the actual account database or restart a running service.

Existing code/risk identity checks continue to require compatible qualification evidence after source changes; old approvals are not automatically transferred to the upgraded version.

Five-minute samples do not provide a continuous order-book history. Depth probes exclude fees, are limited to the recorded levels, and cannot guarantee an actual fill. The 14-day archive is bounded operational evidence; longer studies require a separate export/retention design. Realized execution differences combine movement and impact, which these observations cannot separate. Current quote samples cannot reconstruct historical spreads in the saved development study.

Next: register a small development-only experiment for reduced turnover/stronger entry selectivity, while gathering quote evidence. Keep the final-test period sealed until a candidate passes development and chronological validation.
