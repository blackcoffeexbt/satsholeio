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
- Balanced opponents match player speed and receive 115% object growth mass;
  aggression also scales speed, growth, perception and reactions. Relentless moves
  at 158% player speed and receives 190% object growth mass.
- Populated parks with trees and low walls, walking pedestrians and dogs.
- Ten competitor aggression levels, from Passive to Relentless (default Balanced).
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
- Frozen prize plans, native Lightning Address payouts, refunds and append-only outgoing receipts.
- Configurable review delay and carry-forward/hold policy for unclaimed podium shares.
- Reasoned player blocking, entry disqualification/refunds and recoverable operator audits.
- Private run/replay inspection, observational anomaly flags, emergency pause, payment holds and guarded destination repair.

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

Broader production verification, device performance/balance sampling, PostgreSQL
verification and resolution of retained unallocated prizes under the optional hold
policy. Automatic transfers default to disabled.
Real incoming and outgoing invoice settlement must be tested against the operator's configured wallet.

## Troubleshooting

### Official run shows `INVALID` after verification

If an official game finishes but shows `INVALID` or “Replay could not verify this
input log”, it cannot be submitted to the leaderboard. One possible cause is an
outdated Node.js runtime used by the LNbits server. For example, older versions
can fail with `Cannot find module 'node:fs'` before replay verification starts.

**The LNbits server process must use Node.js 18 or later.** Node.js 24 LTS or a
newer supported LTS release is recommended. Check the version and executable in
the environment where LNbits actually runs:

```sh
node --version
command -v node
```

A terminal can use a different Node installation from the LNbits service. For
container deployments, check and update Node inside the container. Install a
compatible version, configure the LNbits service to use its executable through
its `PATH`, and restart LNbits. Updating the interactive shell alone may not fix
server verification.

Check the LNbits logs for `SatsHole verifier`. These entries show the executable,
Node runtime version, verifier path, exit code and error output. After updating,
play a new official run and confirm verification succeeds with `exit=0`.
Previously `INVALID` runs are not reverified by the Retry verification button.

`INVALID` can also indicate rejected replay inputs or a verification timeout. If
LNbits already uses a compatible Node version, use the verifier logs to diagnose
the failure rather than assuming every invalid run is a Node version issue.

## Tests

`node --test tests/simulation.cjs`

Using the LNbits Python environment, `python tests/game_backend.py` and
`python tests/competition_backend.py`, `python tests/settlement_backend.py` and
`python tests/moderation_backend.py`.
Backend and simulation tests
cover replay, invoice recovery, duplicate receipts, weekly snapshots and DST. Integration
checks use a temporary database and fake Lightning I/O; no real funds move.

`node tests/fairness.cjs 1000` samples full-duration seeds with a simple baseline bot.
`node verify.cjs < satshole-replay.json` verifies an exported practice replay.

After a week closes, settlement waits one hour by default. In Operations, freeze the
prize plan to review recipients and amounts, then pay prizes. Retry/reconcile uses the
same persisted invoice and payment hash. Uncertain sends are checked against native
LNbits outgoing records. Destination repair is explicit and audited. For an attempted invoice, replacement
requires expiry and final failure confirmed by both LNbits and the funding source.
Pending or uncertain outcomes refuse replacement; repaired obligations remain held
until the operator releases them. Receipt-only reconciliation never sends.
Late and duplicate receipts refund to the entry's saved Lightning Address. Missing
podium shares default to the current open week; the optional hold policy retains
those sats as an unresolved liability. Routing fees are recorded separately and use
additional wallet balance; award principal never exceeds its prize allocation.

In Run and entry review, inspect committed runs, replay them on the server or
export their original versioned inputs. Replay inspection never rewrites scores.
Block/unblock players or disqualify/restore entries before the prize plan freezes.
Disqualification alone preserves paid allocations. Disqualify-and-refund moves the
full entry fee into a refund liability and cannot be reversed. Frozen rankings and
awards remain fixed even if a player is subsequently blocked. Every review action
requires a reason and records the operator identity; review flags identify stored
replay inconsistencies, copied seed/input commitments and repeated rejections
without automatically taking moderation actions; interrupted actions recover
from the audit journal. Emergency pause stops new games, entries and automatic
settlement, while operators can still reconcile receipts or explicitly send funds.

See `DEVELOPMENT.md` for implementation status and remaining milestones.
