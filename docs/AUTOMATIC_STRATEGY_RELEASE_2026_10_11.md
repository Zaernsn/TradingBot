# Automatic strategy promotion and Strategy Lab

The later [faster research release](FASTER_AUTOMATIC_RESEARCH_2026_10_11.md)
supersedes this document's hourly cadence, seven-day minimum and pilot exposure
limits. This document records the earlier release.

Supersedes the manual-approval policy in STRATEGY_LEARNING_IMPLEMENTATION_2026_10_11.md
at the user's explicit request. No account mode, running flag or risk setting is changed.

## Automatic lifecycle

Historical gates → forward paper tests → one limited-live controller → live approval.
No manual approval step remains, including for records carrying the earlier manual flag.
Strategy/code/risk freezing and existing evidence gates remain enforced. The initial
live stage permits at most two positions and 25% aggregate exposure, bounded further
by saved risk limits. Actual live orders still require the existing live-enabled
account configuration. Ten reconciled exits with non-positive aggregate P&L now
suspend the trial; positive aggregate P&L passes the existing canary promotion gate.

The original 29-candidate search can now produce follow-up generations: up to eight
new parameter identities per batch, at most 12 follow-up generations (125 identities
including the initial budget). Parents come from the previous generation; selection
uses frozen development results, never final-test scores. A new generation waits
at least 336 hours beyond the prior generation's newest test endpoint. Its final
test starts after that endpoint. Pending parameter batches are persisted and resumed
across hourly passes/restarts. Duplicate identities are skipped; the system may wait
if no novel bounded mutation exists. This remains finite, not unlimited optimization.
Historical rejections can still receive bounded fresh-data retests. Failed shadow
ledgers remain intact. No historical result guarantees profitability.

## Dashboard

Strategy Lab replaces the previous release card: four-stage pipeline, status and
budget counters, accessible status filters, expandable candidate evidence,
plain-language rejection reasons, live suspension reasons and responsive layout.
It reuses the existing research response and is memoized against the dashboard's
one-second clock updates; no additional polling or market requests are added.

## Known limitation

Full backend verification still includes an unrelated pre-existing liquidity-message
spelling mismatch (`maxximum`). That local user edit is preserved.

## Verified deployment

- Strategy regression suite: 23 passed.
- Full backend suite: 252 passed; the one known wording mismatch failed.
- Frontend type checking, Strategy Lab rendering tests, tracked-coin tests and
  production build passed. Rendering tests are not a browser screenshot review.
- Docker Compose rebuilt and recreated backend/frontend; database volume retained.
- API returned `ok`, frontend HTTP 200, and all five running bots reported HEALTHY
  protection after restart. No account risk settings or running flags were edited.
