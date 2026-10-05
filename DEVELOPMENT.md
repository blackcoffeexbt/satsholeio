# Bitcoin Borough status

Milestones 1–3 have a playable 3D foundation: original city, client AI, integer
simulation at 20 Hz, deterministic input replay, historical city-1/city-2/city-3 engine support,
seeded district-based city-4 map, spatial indexing and a headless fairness harness.
Fairness/balance and full-duration device performance still require larger samples.

Milestones 4–6 now have wallet-owned settings, additive database migration, pseudonymous
cookie identity, single-use server-created runs, native play invoices, introductory
free runs, server replay and idempotent game revenue records. Available runs can be
retrieved before start; seeds are never returned by status endpoints. Final input is
committed once and operational retries cannot change it. An interrupted verification
returns to FINISHED_UNVERIFIED on extension restart. Two Node workers, a 128 MB heap
limit, 30-second timeout and a 256 KB request limit bound replay work.

Practice uses browser-created seeds and unlimited runs. It is separate from official
server-owned runs. Practice scores cannot enter the weekly leaderboard.
Configured wallet changes are intentionally unavailable after first setup; a future
operator migration must preserve run and financial ownership.

Native invoice callbacks and status reconciliation both bind receipts to wallet,
hash, amount and run. Native invoice external_id supports recovery if the process
stops between invoice creation and saving its payment hash. Financial events are
unique by receipt hash. Game revenue is recorded separately from wallet balance.

Milestone 7 adds weekly configuration snapshots, DST-safe close, paid verified-score
entry, unique-player best-score ranking, receipt-order ties and public historical
leaderboards. Entry invoices are separate from play invoices. A receipt confirmed
before close creates one entry and an immutable prize/operator allocation; late or
additional receipts become full refund liabilities. Separate invoice attempts support
renewal and recovery after interrupted creation or receipt recording. Operator metrics
show prize/refund liabilities and wallet balance less those liabilities before fees.

Milestone 8 adds frozen settlement plans, a default one-hour review delay, native
Lightning Address payouts and refund transfers. Invoices and payment hashes persist
before sending; uncertain attempts reconcile native outgoing records and reuse the
saved invoice. Immutable outgoing receipts reduce liabilities only after success
and record native fees. Missing podium shares carry to the open week by default,
or remain held. Operator controls freeze, review, send and retry. Automatic
maintenance is opt-in and remains disabled. No fresh invoice is silently substituted after an attempted send.

Milestone 9 adds wallet-authenticated run inspection and replay/export, player
blocking, entry disqualification/restore and full entry refunds before settlement
freezes. Audited refund adjustments preserve original receipts and reclassify both
prize and operator allocations into refundable liabilities. The immutable journal
records actor, reason, action ID and before/after facts. Idempotent projections
recover interrupted actions before a settlement plan or outgoing send proceeds.
Observational flags highlight missing/mismatched replay records, repeated failures
and shared seed/input commitments without automatic moderation. Frozen rankings
now persist alongside the award plan; legacy plans retain their
recorded podium. Blocking does not alter those frozen awards.

Payment holds pause sending but allow success reconciliation. Receipt-only checks
never request or send an invoice. Explicit destination repair leaves the obligation
held, with the original invoice and hash in the audit. Previously attempted invoices
require expiry, a failed native record and a fresh final failure from the funding
source. Pending, unknown or completed attempts cannot receive replacement invoices.
Emergency pause disables new games, entries and automatic settlement. Current-week
and outgoing metrics are calculated from persisted server records.

Verification uses the real LNbits SQLite abstraction with fake Lightning I/O,
including recovery, permissions, refund conservation and invoice replacement guards.
Python lint/format and JS syntax checks pass. The live public page loads on :5001;
the operator UI is visually checked with isolated demo data. Actual Lightning
payments, authenticated live admin interaction and PostgreSQL still need
verification. Automatic transfers remain disabled.

Remaining work is production hardening: broader balance/device samples, audited
release of retained unallocated prize liabilities, live payment/restart tests and
PostgreSQL checks. Milestones 1–9 have their core extension workflows implemented.

City-3 replaces some street-grid interiors with multi-block parks, a pond, a campus
and a parking area. Traffic routes exclude removed road corridors; parked cars and
cone groups retain their positions on respawn. New terrace and large-landmark tiers
extend the consumption ladder. AI moves at 9 units/tick versus the player’s 12 and
gains 55% object mass. Twenty-four bitcoins award 120 points each. Building support
loss, directed toppling and gravitational descent are presentation animations, not
a rigid-body collision solver; authoritative collection still uses integer simulation.
Archived city-2 replays remain verifiable. New tests cover layout, moving traffic,
cone groups, reduced AI growth and archived replay compatibility.

City-4 merges roughly half the map into 18+ districts, including larger residential
courtyards, and ranges building heights from low shops to 600+ unit towers. AI now
moves at 10 units/tick and gains 75% object mass, steering every six ticks. Traffic
uses surviving road segments and reverses at their ends. Released browser engines
use immutable versioned filenames; available runs load their recorded version before
START, and historical replay versions remain available.

City-5 adds park tree clusters, low perimeter walls, dogs, and deterministic path
walking with interpolated poses and stride animations. Competitor aggression is an
integer 1–10, default 5 (Balanced), validated in settings and replay. It controls
prey targeting, pursuit range, threat avoidance and steering frequency. Official
competitions snapshot it; practice receives the live setting. Historical city-4
engines remain unchanged. Tests cover walker routes and aggression behavior.

City-6 makes aggression a difficulty scale: levels 1/5/10 use speeds 8/10/12,
growth percentages 55/75/100, object search radii 540/900/1350 and steering intervals
10/6/2 ticks. All levels evade larger threats; high levels also hunt more actively.
Practice refreshes live settings before each run. City-5 replays remain supported.

City-7 strengthens difficulty: levels 1/5/10 use speeds 8/12/19, growth percentages
55/115/190, search radii 630/1150/1800, and reaction intervals 10/6/1 ticks. Target
selection values growth plus score per travel time to the collectible edge, and
hunting anticipates prey movement. Every-tick steering uses a zero-based modulo
check. Previous city-6 replay files remain immutable. Across three stationary-player
benchmark seeds, level-10 mean AI score rose from 43,998 to 49,032, and mean surviving
mass from 54,440 to 95,627. Human playtesting is still required for final balance.
