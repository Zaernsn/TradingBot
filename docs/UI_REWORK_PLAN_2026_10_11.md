# UI rework plan — intuitive operation and safer setting guidance

## 1. Outcome

The reworked UI should let a user answer these questions in under ten seconds:

1. Is the bot safe, connected, and up to date?
2. Can it open a new position right now?
3. If not, what is the first blocking reason and what should I do?
4. What is currently at risk in EUR, not only in percentages?
5. Which settings are appropriate for paper testing or cautious live operation?

“Recommended” must mean a conservative operational default, not a promise of profit.
The product currently states that profitability has not been established, so the UI
must never label a strategy as “best” or imply expected returns.

## 2. Problems found in the current UI

- The dashboard combines bot controls, research, Kraken history, the market scanner,
  positions, signals, and trades in one long page.
- The primary operating question — “can the bot buy?” — has to be inferred from
  mode, bot state, health, entry halts, protection state, research state, and per-coin
  decisions.
- Strategy research is presented before the account and tracked markets even though
  it is an expert workflow.
- Settings places presets and more than twenty interacting fields in one form. The
  user is told that the smallest limit wins, but is not shown which limit wins.
- The two existing presets are hard-coded for a EUR 100 wallet, while the current
  wallet/equity may be different.
- “Recommended live” is too strong without showing suitability, effective EUR risk,
  and the fact that historical profitability has not been established.
- Preset application, saving settings, enabling Live, and starting the bot are four
  separate actions, but the current flow does not make that sequence easy to follow.
- Emergency stop is immediate. Its exact effect should be explained before the user
  confirms: stop new orders and reconcile pending ones; do not liquidate holdings.
- Recovery, credentials, backtesting, live activation, and paper-data deletion are
  mixed into the same Settings page.
- The README mentions a Fast meme preset that is not present in the current frontend.
  The UI and documentation must be reconciled before exposing preset guidance.

## 3. Target information architecture

Use four primary destinations. Keep the existing visual language, but replace the
two-link navigation with a desktop sidebar and a compact mobile bottom navigation.

| Destination | Primary job | Existing content moved here |
| --- | --- | --- |
| Overview | Operate and understand the bot now | portfolio summary, operating status, blockers, open positions, latest activity |
| Markets | Understand what the bot is watching | tracked coins, filters, signals, per-market entry decisions |
| Strategy Lab | Inspect research evidence | strategy candidates, shadow/canary progress, backtest |
| Settings | Configure safely | strategy profile, risk limits, Kraken, Live activation, recovery, destructive actions |

### Overview hierarchy

Above the fold:

1. Mode badge: `Paper`, `Live`, or `Live unavailable`.
2. Plain-language state: `Ready to evaluate entries`, `Waiting`, or `Action needed`.
3. Readiness chain: `Kraken → Account sync → Bot → Market data → Strategy → Entry`.
4. First blocker with one recommended action.
5. Equity, available cash, invested amount, open positions, and today’s realized P/L.
6. Primary control: Start/stop bot. Emergency stop remains visually separate.

Below the fold:

1. Open positions with active stop, target, and age.
2. Recent decisions: buys, sells, blocked entries, and errors in one timeline.
3. Compact Kraken balance/history card with a link to details.

Do not show Strategy Lab candidate internals or the entire tracked-market table on
Overview.

### Markets hierarchy

- Summary strip: tracked, eligible, buy candidates, blocked, held.
- Default filter: `Actionable`, not `All tracked`.
- Each row starts with a human result: `Eligible`, `Waiting for candle`, `Spread too
  wide`, or `Model retraining`.
- Expand a row for current value, required value, last check, signal evidence, and raw
  diagnostics.
- Preserve search and sorting, but replace the very wide mobile table with stacked
  cards.

### Strategy Lab hierarchy

- Pipeline: `Research → Validation → Holdout → Shadow → Canary → Live`.
- One highlighted card for the active or next candidate.
- Progress uses `current / required`, for example `12 / 30 shadow trades` and
  `4 / 7 forward days`.
- Translate every failed check into plain language; raw check codes live in an
  expandable Diagnostics section.
- Move backtesting here and explain that a backtest is evidence, not a live-trading
  approval.

### Settings hierarchy

Replace the long page with five routed or tabbed sections:

1. **Guided setup** — goal, mode, wallet size, risk comfort, suggested profile.
2. **Strategy & markets** — entry strategy, memecoin toggle, discovery/watchlist.
3. **Risk & exits** — position size, exposure, stops, loss halts, holding time.
4. **Kraken & Live** — credentials, connection test, preflight, live enable/disable.
5. **Advanced & recovery** — fees, slippage, model threshold, uncertain orders,
   baseline resets, paper reset.

Advanced and destructive controls should not appear in the default Settings view.

## 4. Guided settings experience

### Step 1 — choose intent

Offer three profiles:

| Profile | User-facing description | Availability |
| --- | --- | --- |
| Learn in Paper | Safest place to observe decisions; no real orders | Always recommended for new or changed configurations |
| Cautious Live | Low exposure and liquid/core markets | Only after connection and preflight pass |
| Experimental | Broader discovery or automatic research; higher uncertainty | Paper by default; Live requires explicit risk acknowledgement |

Avoid “aggressive but recommended”. Use `Experimental — high risk` and keep it out
of the primary path.

### Step 2 — calculate, do not hard-code, wallet guidance

Use current equity as the basis and show both percentage and EUR values. The existing
EUR 100 preset can remain as a named example only when equity is close to EUR 100.

For every profile show:

- maximum per position in `%` and `EUR`;
- maximum total exposure in `%` and `EUR`;
- cash reserve in `%` and `EUR`;
- planned loss at the stop in approximate `EUR`;
- maximum concurrent positions;
- stop, target, and time-exit behavior;
- markets included and liquidity requirements.

Example preview for EUR 100:

> Cautious Live can invest at most EUR 20 per position and EUR 40 in total, leaving
> at least EUR 60 unallocated before fees. A 4% stop on a EUR 20 position represents
> about EUR 0.80 before gaps, slippage, and fees.

This is an explanation of configured ceilings, not a loss guarantee.

### Step 3 — show suitability and evidence

Every suggestion card needs three separate labels:

- **Risk level:** cautious, elevated, high.
- **Operational status:** available, missing Kraken connection, paper testing needed,
  or blocked.
- **Evidence status:** unproven, paper evidence, shadow evidence, canary, or live
  approved.

Never merge these labels into one green “recommended” badge.

### Step 4 — explain the effective limit

Add an `Effective order limit` calculator. It should list each ceiling and highlight
the smallest one:

```text
Configured trade cap                 EUR 20.00
Position exposure cap (20%)         EUR 20.00
Remaining portfolio exposure        EUR 13.40  ← effective limit
Memecoin per-coin cap               not applicable
Cash after fee/slippage reserve      EUR 58.92
```

If the estimated order falls below Kraken’s minimum, explain that the bot will wait.
The backend remains authoritative; the frontend preview must be labelled an estimate.

### Step 5 — review changes before save

When settings change, use a sticky summary bar:

- `6 unsaved changes`;
- `Estimated total exposure: EUR 40 → EUR 75`;
- `Risk increased` or `Risk reduced`;
- `Review changes` and `Discard` actions.

The review dialog groups changes by consequence, not field name. Increases to
position size, exposure, trade frequency, tolerated drawdown, spread, or memecoin
access require explicit confirmation. Saving settings must never enable Live or start
the bot.

### Step 6 — provide a safe activation checklist

After saving, show the next incomplete step:

1. Save profile.
2. Connect Kraken with no withdrawal permission.
3. Test connection.
4. Pass dedicated-account/reconciliation preflight.
5. Enable Live with an explicit confirmation.
6. Start the bot separately.

Each step should link to the correct section and show why it is blocked.

## 5. Hint and copy system

Create one shared catalogue for labels, explanations, severity, and actions. Do not
scatter wording across components.

Each setting should support four layers:

1. **Label** — plain language, for example `Maximum invested at once`.
2. **One-line hint** — `Caps all open positions combined.`
3. **Live preview** — `40% of EUR 100 = EUR 40`.
4. **Learn more** — dependencies, edge cases, and server enforcement.

Recommended copy rules:

- Say `new buys paused`; do not say only `risk_halt`.
- Say `2 of 30 required test trades`; do not expose only a failed-check code.
- Say `waiting for the next completed hourly candle`; do not say only
  `waiting_candle`.
- Always pair `current`, `required`, `why it matters`, and `next action`.
- Use color as reinforcement, never as the only signal.
- Raw codes and JSON belong under `Diagnostics`.

## 6. Safety-critical interactions

### Start/stop versus emergency stop

- **Stop bot:** stops the normal loop; explain the state of protective monitoring.
- **Emergency stop:** confirmation dialog states that new orders stop and uncertain
  orders are reconciled; holdings are not automatically sold.
- Show a persistent banner for unresolved/unknown orders, reconciliation failures,
  unpriced balances, stale protection checks, or balance mismatches.
- Critical banners must remain visible across Overview, Markets, and Settings until
  resolved.

### Live enable dialog

Show a preflight list before the final button:

- server allows Live;
- credentials saved and connection tested;
- withdrawal permission warning acknowledged;
- account/book reconciliation passed;
- current profile and maximum EUR exposure shown;
- profitability disclaimer acknowledged.

### Destructive actions

Move paper reset and baseline resets to `Advanced & recovery`. Use a typed or
two-step confirmation, state exactly what is deleted or preserved, and keep the bot
stop requirement visible before interaction.

## 7. Technical implementation plan

### Phase 0 — contracts and wording (small, no layout rewrite)

- Add `frontend/src/lib/statusCopy.ts` for status and failure-code translations.
- Add pure helpers in `frontend/src/lib/riskPreview.ts` for EUR previews, effective
  limits, risk direction, and changed-field summaries.
- Reconcile the missing Fast meme preset between README and frontend.
- Correct existing copy defects such as `TRADING WORKSPACEE`.
- Define one severity model: `info`, `waiting`, `action`, `blocked`, `critical`.

Acceptance:

- No snake_case status is visible in default views.
- Unit tests cover every known blocker and all preset calculations.
- Preset names and values have one source of truth.

### Phase 1 — Overview and readiness

- Add `components/LiveReadiness.tsx`.
- Add `components/PrimaryBlocker.tsx`.
- Add `components/SafetyBanner.tsx` at Layout level.
- Replace the immediate emergency action with `EmergencyStopDialog.tsx`.
- Reduce Dashboard to operational summary, open positions, and activity timeline.

Backend/API addition:

- Prefer a structured readiness response with ordered steps, severity, current value,
  required value, checked time, and safe action. Do not duplicate trading decisions in
  the frontend.

Acceptance:

- The first failed readiness step and one next action are visible without scrolling
  at 360, 768, 1280, and 1600 px.
- Emergency stop cannot be triggered without seeing its consequences.

### Phase 2 — split Markets and Strategy Lab

- Add routes `/markets` and `/strategy-lab`.
- Move `TrackedCoins` to Markets and provide responsive market cards.
- Move `StrategyLearning` and Backtest to Strategy Lab.
- Add translated evidence rows and candidate progress.

Acceptance:

- Overview no longer contains the full market/research tables.
- A user can find a blocked coin’s current value, required value, and next check.
- Candidate state is understandable without opening Diagnostics.

### Phase 3 — guided Settings

- Split `Settings.tsx` into route-level sections and focused components.
- Add `ProfileChooser`, `RiskImpactPreview`, `EffectiveLimits`, `UnsavedChangesBar`,
  and `SettingsReviewDialog`.
- Fetch portfolio equity on Settings so all percentages have EUR previews.
- Track the last saved settings object separately from the editable draft.
- Add field-level validation and focus the first invalid input after a failed save.

Backend/API addition:

- Add a read-only risk-preview endpoint that returns authoritative effective caps,
  exchange minimum status, fee/slippage reserve, and applicable canary limits for a
  draft configuration.
- Return machine-readable field errors and a risk-change classification.

Acceptance:

- A new user can select Paper or Cautious Live, understand the EUR impact, save, and
  see the next activation step without reading advanced fields.
- Increasing risk always produces a review summary.
- Saving does not enable Live or start trading.

### Phase 4 — Kraken, Live, and recovery flow

- Build a checklist-driven Kraken & Live page.
- Remember the last successful connection-test time and show when it becomes stale.
- Present recovery records as plain-language incidents with expandable measurements.
- Separate routine configuration from resets and paper-history deletion.

Acceptance:

- Live activation shows the exact profile and maximum EUR exposure.
- Unknown orders and reconciliation failures are never hidden by normal messages.
- Recovery actions are disabled with a visible reason while the bot is running.

### Phase 5 — responsive, accessibility, and polish

- Replace horizontal tables with mobile cards for positions, markets, trades, and
  orders.
- Add consistent loading, empty, error, stale, and partial-data states.
- Use relative time plus an exact timestamp with timezone.
- Verify keyboard flow, focus trapping/restoration, headings, live regions, and
  reduced-motion behavior.
- Add visual regression checks at 360, 768, 1280, and 1600 px in light/dark themes if
  both themes are supported.

## 8. Suggested component and route map

```text
App
└─ Layout
   ├─ SafetyBanner
   ├─ Navigation
   └─ Routes
      ├─ /                 OverviewPage
      │  ├─ OperatingHero
      │  ├─ LiveReadiness
      │  ├─ PrimaryBlocker
      │  ├─ PositionSummary
      │  └─ ActivityTimeline
      ├─ /markets          MarketsPage
      │  ├─ MarketSummary
      │  ├─ MarketFilters
      │  └─ MarketTable / MarketCards
      ├─ /strategy-lab     StrategyLabPage
      │  ├─ ResearchPipeline
      │  ├─ CandidateEvidence
      │  └─ BacktestPanel
      └─ /settings/*       SettingsLayout
         ├─ guided
         ├─ strategy
         ├─ risk
         ├─ kraken-live
         └─ advanced-recovery
```

## 9. Testing plan

Unit tests:

- blocker/status translations;
- profile calculations for EUR 80, EUR 100, EUR 500, and missing equity;
- minimum-of-limits calculation;
- risk increase/decrease classification;
- unsaved-change detection;
- exact preset values and documentation consistency.

Component tests:

- readiness chain selects only the first actionable blocker;
- emergency dialog copy and confirmation;
- settings review and cancellation;
- Live activation checklist;
- mobile market/position cards;
- field-level API errors and restored focus.

End-to-end flows:

1. New user → Paper profile → save → start bot.
2. Save Kraken credentials → test → preflight blocked with explanation.
3. Cautious Live → review EUR risk → enable Live → explicitly start.
4. Entry halted → identify cause → stop bot → perform allowed recovery.
5. Unknown order → persistent critical banner → no new-entry action available.

## 10. Delivery order and scope

Ship in five reviewable increments:

1. **Status language and readiness** — highest clarity/safety impact.
2. **Overview split** — move Markets and Strategy Lab to their own routes.
3. **Guided Settings and EUR previews** — highest usability impact.
4. **Live/recovery flow** — highest operational-risk impact.
5. **Mobile/accessibility hardening** — release gate before calling the rework done.

Do not combine this with changes to trading logic, strategy thresholds, or server-side
safety enforcement. The UI may explain and preview those rules; the backend must
remain authoritative.

## 11. Definition of done

- A first-time user can choose a safe Paper profile without opening Advanced.
- “Can the bot buy?” is answered with one state, one first blocker, and one next step.
- Every percentage that affects money also shows an estimated EUR value.
- “Recommended” never implies profitability and always includes suitability and risk.
- Effective limits explain which cap is controlling an order.
- Live activation, bot start, stop, and emergency stop are clearly distinct actions.
- No technical status code is shown outside Diagnostics.
- Critical order/reconciliation states persist across relevant pages.
- All core flows work with keyboard and screen reader and at 360 px width.
- Frontend tests and production build pass, with no weakening of backend safeguards.
