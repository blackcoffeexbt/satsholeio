# SatsHole · Bitcoin Borough

An LNbits extension with an original 3D city-eating arcade game and deterministic
server replay. Single player, eight client-side AI opponents by default.

## Local setup

Enable the `satshole` extension in LNbits. Node.js 18+ must be available to the
LNbits server process for replay verification. No new Python dependencies.

Open the extension from your LNbits wallet to configure it. An LNbits administrator
must perform initial setup. Select the receiving wallet and save settings. Future
configuration requires that same wallet's admin key. Official games are paused
until configuration exists.

Public page: `/satshole/play` (no LNbits account needed).

Defaults: 25 sats per paid attempt, three introductory free attempts, 120 seconds,
eight AI opponents, 20% death score penalty. Unlimited practice is separate from
introductory official runs and cannot qualify for the paid leaderboard by default.

## Implemented

- 3D city, angled camera, keyboard/mouse/touch controls, arcade audio.
- Fixed 20 Hz deterministic engine, spatial indexing, replay-compatible versioning.
- Pavement-only people/furniture/trees, growth progress arc, interpolated rendering.
- Seeded merged parks/ponds, terraced streets, varied towers and large landmarks.
- Moving road traffic, parked cars, curb-aligned five-cone rows and rare 120-point bitcoins.
- Opponents move at 83% player speed and receive 75% object growth mass.
- Floating collection scores and directional support-loss/gravity fall animations.
- HttpOnly player identity cookie, chosen display name, free-run quota.
- Native LNbits invoices, QR/copy/wallet payment actions, receipt reconciliation.
- Server-created seed revealed only after an atomic one-use START.
- Snapshotted run rules, expiring invoices and available attempts.
- Server replay produces the authoritative score; arbitrary client scores rejected.
- Immutable final-input commitment, bounded replay workers, operational retry.
- Append-only idempotent game revenue records and operator metrics.
- Weekly competitions with frozen rules and a DST-aware Sunday 21:00 close.
- Paid verified-score entries, one best score per player, and historical leaderboards.
- Default 80/20 prize/operator allocation and estimated 70/20/10 podium prizes.
- Separate invoice attempts, duplicate-payment refund liabilities and recovery.

Leaderboard entry defaults to disabled. The operator can configure it separately
from paid play. Entry is accepted only when the extension first confirms payment
before the weekly cutoff; an unpaid invoice does not reserve a place. Late receipts
and additional payments for the same entry are recorded in full as refund liabilities.
Tied scores use the first accepted entry. Financial and game rules are frozen for
each week; pauses take effect immediately.

Closing or refreshing after START forfeits the attempt. A paid READY attempt remains
available until its configured expiry. Confirmed late invoice payments grant the
purchased attempt. Clearing cookies creates a new pseudonymous identity; introductory
free games are a browser allowance, not a proof of unique human identity.

## Still in development

Automatic prize payouts, carry-forward, refund transfers and operator fraud tooling.
The current ledger records liabilities but does not send these payments.
Real invoice settlement must be tested against the operator's configured wallet.

## Tests

`node --test tests/simulation.cjs`

Using the LNbits Python environment, `python tests/game_backend.py` and
`python tests/competition_backend.py`. The 18 backend and 14 simulation tests
cover replay, invoice recovery, duplicate receipts, weekly snapshots and DST. Integration
checks use a temporary database and fake Lightning I/O; no real funds move.

`node tests/fairness.cjs 1000` samples full-duration seeds with a simple baseline bot.
`node verify.cjs < satshole-replay.json` verifies an exported practice replay.

See `DEVELOPMENT.md` for implementation status and remaining milestones.
