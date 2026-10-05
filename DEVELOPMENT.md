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

Verification checks: 14 Node simulation tests and 18 backend integration tests
against the real LNbits SQLite abstraction. Backend tests fake Lightning I/O. Python
lint/format and JS syntax checks pass. The public page loads on local LNbits :5001.
Actual Lightning payment, authenticated admin interaction and PostgreSQL deployment
still need environment-specific verification.

Next: milestones 8–9 — idempotent payouts, carry-forward, refund transfers,
blocking/disqualification and payout operational controls.
Only then enable cash competition features. No automatic settlement before those
invariants and restart/idempotency tests pass.

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
