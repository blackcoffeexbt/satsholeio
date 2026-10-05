"""Frozen settlement plans and durable, invoice-pinned outgoing payments."""

import asyncio
import json
from uuid import uuid4

from bolt11 import decode
from fastapi import HTTPException
from lnbits.core.crud import get_standalone_payment
from lnbits.core.services import pay_invoice
from lnbits.core.services.lnurl import get_pr_from_lnurl

from . import competitions as comp
from . import game_service as game
from .crud import db

_lock = asyncio.Lock()


async def plan(competition_id, automatic=False):
    await comp.current_competition()
    async with db.connect() as conn:
        existing = await conn.fetchone(
            "SELECT * FROM satshole.settlements WHERE competition_id=:id",
            {"id": competition_id},
        )
        if existing:
            return dict(existing)
    competition = await comp.competition_by_id(competition_id)
    config = json.loads(competition["config"])
    if competition["status"] == "OPEN" or game.now() < competition[
        "ends_at"
    ] + config.get("settlement_delay", 3600):
        raise HTTPException(
            409, "The competition must close and finish its review delay first."
        )
    # One insert contains the complete immutable allocation.
    async with _lock:
        from .moderation import recover_unlocked

        await recover_unlocked()
        if automatic and not (await game.game_config())["automatic_payouts"]:
            raise HTTPException(409, "Automatic settlement is paused.")
        existing = await db.fetchone(
            "SELECT * FROM satshole.settlements WHERE competition_id=:id",
            {"id": competition_id},
        )
        if existing:
            return dict(existing)
        ranked = await comp.ranking(competition_id)
        total = (await comp.totals(competition_id))["prize_liability"]
        amounts = comp.prizes(total, config)
        winners = []
        for position, row in enumerate(ranked[:3]):
            submission = await db.fetchone(
                "SELECT payout_address FROM satshole.submissions WHERE run_id=:id",
                {"id": row["run_id"]},
            )
            if amounts[position]:
                winners.append(
                    {
                        "id": str(uuid4()),
                        "position": position + 1,
                        "player_id": row["player_id"],
                        "display_name": row["display_name"],
                        "score": row["score"],
                        "address": submission["payout_address"],
                        "amount": amounts[position],
                    }
                )
        target = await comp.current_competition()
        carry = total - sum(w["amount"] for w in winners)
        data = {
            "id": competition_id,
            "plan": json.dumps(winners),
            "rankings": json.dumps(ranked),
            "pot": total,
            "carry": carry,
            "target": (
                target["id"]
                if config.get("undistributed_policy", "carry") == "carry"
                else competition_id
            ),
            "time": game.now(),
        }
        await db.execute(
            """INSERT INTO satshole.settlements
(competition_id,plan,pot,carry_amount,carry_to,created_at,rankings) VALUES
(:id,:plan,:pot,:carry,:target,:time,:rankings) ON CONFLICT (competition_id) DO
NOTHING""",
            data,
        )
        await db.execute(
            "UPDATE satshole.competitions SET status='PAYING' WHERE id=:id",
            {"id": competition_id},
        )
        return dict(
            await db.fetchone(
                "SELECT * FROM satshole.settlements WHERE competition_id=:id",
                {"id": competition_id},
            )
        )


async def obligation(key, kind, competition_id, wallet, address, amount):
    await db.execute(
        """INSERT INTO satshole.outgoing
        (id,kind,competition_id,wallet_id,address,amount,status,created_at)
        VALUES (:id,:kind,:competition,:wallet,:address,:amount,'READY',:time)
        ON CONFLICT (id) DO NOTHING""",
        {
            "id": key,
            "kind": kind,
            "competition": competition_id,
            "wallet": wallet,
            "address": address,
            "amount": amount,
            "time": game.now(),
        },
    )


async def confirm_outgoing(row, payment):
    await db.execute(
        """INSERT INTO satshole.outgoing_receipts
        (outgoing_id,payment_hash,kind,competition_id,amount,fee_msat,paid_at)
        VALUES (:id,:hash,:kind,:competition,:amount,:fee,:time)
        ON CONFLICT (outgoing_id) DO NOTHING""",
        {
            "id": row["id"],
            "hash": row["payment_hash"],
            "kind": row["kind"],
            "competition": row["competition_id"],
            "amount": row["amount"],
            "fee": abs(getattr(payment, "fee", 0) or 0),
            "time": game.now(),
        },
    )
    await db.execute(
        "UPDATE satshole.outgoing SET status='PAID',error=NULL WHERE id=:id",
        {"id": row["id"]},
    )
    if row["kind"] == "PRIZE":
        frozen = await db.fetchone(
            "SELECT plan FROM satshole.settlements WHERE competition_id=:id",
            {"id": row["competition_id"]},
        )
        if frozen:
            recorded = await db.fetchone(
                """SELECT COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN status!='PAID' THEN 1 ELSE 0 END),0) AS pending
                FROM satshole.outgoing WHERE competition_id=:id AND kind='PRIZE'""",
                {"id": row["competition_id"]},
            )
            if (
                recorded["total"] == len(json.loads(frozen["plan"]))
                and not recorded["pending"]
            ):
                await db.execute(
                    "UPDATE satshole.competitions SET status='SETTLED' WHERE id=:id",
                    {"id": row["competition_id"]},
                )


async def transfer(key, automatic=False, send=True):
    # All workers and manual requests share this lock. Pending/unknown attempts only
    # reconcile; retries always reuse the persisted invoice and payment hash.
    async with _lock:
        from .moderation import recover_unlocked

        await recover_unlocked()
        row = dict(
            await db.fetchone(
                "SELECT * FROM satshole.outgoing WHERE id=:id", {"id": key}
            )
        )
        paused = (
            not send
            or row["held"]
            or (automatic and not (await game.game_config())["automatic_payouts"])
        )
        if row["status"] == "PAID" or (paused and not row["payment_hash"]):
            return row
        try:
            if not row["payment_hash"]:
                invoice = await get_pr_from_lnurl(
                    comp.payout_address(row["address"]), row["amount"] * 1000
                )
                decoded = decode(invoice)
                if int(decoded.amount_msat or 0) != row["amount"] * 1000:
                    raise ValueError("Invoice amount mismatch")
                await db.execute(
                    """UPDATE satshole.outgoing SET bolt11=:bolt,payment_hash=:hash
WHERE id=:id""",
                    {"id": key, "bolt": invoice, "hash": decoded.payment_hash},
                )
                row.update(bolt11=invoice, payment_hash=decoded.payment_hash)
            native = await get_standalone_payment(row["payment_hash"], incoming=False)
            if native and (
                native.wallet_id != row["wallet_id"]
                or abs(native.amount) != row["amount"] * 1000
            ):
                raise ValueError("Native payment ownership mismatch")
            if native and native.success:
                await confirm_outgoing(row, native)
            elif native and native.pending:
                await db.execute(
                    "UPDATE satshole.outgoing SET status='PENDING' WHERE id=:id",
                    {"id": key},
                )
            elif paused:
                return row
            else:
                await db.execute(
                    """UPDATE satshole.outgoing SET status='SENDING',error=NULL,
send_started_at=:time WHERE id=:id""",
                    {"id": key, "time": game.now()},
                )
                payment = await pay_invoice(
                    wallet_id=row["wallet_id"],
                    payment_request=row["bolt11"],
                    max_sat=row["amount"],
                    tag="satshole_" + row["kind"].lower(),
                    external_id=key,
                    extra={"satshole_outgoing_id": key},
                    description="SatsHole " + row["kind"].lower(),
                )
                if payment.success:
                    await confirm_outgoing(row, payment)
                else:
                    await db.execute(
                        "UPDATE satshole.outgoing SET status='PENDING' WHERE id=:id",
                        {"id": key},
                    )
        except Exception:
            # Do not mint a replacement invoice after an uncertain send.
            await db.execute(
                """UPDATE satshole.outgoing SET status='RETRY',error=:error
WHERE id=:id""",
                {
                    "id": key,
                    "error": "Payment unavailable; retry or reconcile saved invoice.",
                },
            )
        return dict(
            await db.fetchone(
                "SELECT * FROM satshole.outgoing WHERE id=:id", {"id": key}
            )
        )


async def settle(competition_id, send=False, automatic=False):
    frozen = await plan(competition_id, automatic=automatic)
    competition = await comp.competition_by_id(competition_id)
    for winner in json.loads(frozen["plan"]):
        await obligation(
            winner["id"],
            "PRIZE",
            competition_id,
            competition["wallet_id"],
            winner["address"],
            winner["amount"],
        )
        if send:
            await transfer(winner["id"], automatic=automatic)
    pending = await db.fetchone(
        """SELECT COUNT(*) AS n FROM satshole.outgoing WHERE competition_id=:id
AND kind='PRIZE' AND status!='PAID'""",
        {"id": competition_id},
    )
    recorded = await db.fetchone(
        """SELECT COUNT(*) AS n FROM satshole.outgoing
        WHERE competition_id=:id AND kind='PRIZE'""",
        {"id": competition_id},
    )
    if not pending["n"] and recorded["n"] == len(json.loads(frozen["plan"])):
        await db.execute(
            "UPDATE satshole.competitions SET status='SETTLED' WHERE id=:id",
            {"id": competition_id},
        )
    return frozen


async def prepare_refunds():
    rows = await db.fetchall(
        """SELECT e.payment_hash,e.competition_id,e.refund_liability AS
amount,s.wallet_id,s.payout_address FROM satshole.competition_events e
JOIN satshole.submissions s ON s.id=e.submission_id WHERE
e.refund_liability>0 UNION ALL SELECT
e.payment_hash,e.competition_id,e.amount,s.wallet_id,s.payout_address
FROM satshole.entry_overpayments e JOIN satshole.submissions s ON
s.id=e.submission_id"""
    )
    for row in rows:
        await obligation(
            "refund:" + row["payment_hash"],
            "REFUND",
            row["competition_id"],
            row["wallet_id"],
            row["payout_address"],
            row["amount"],
        )


async def maintenance():
    await comp.current_competition()
    config = await game.game_config()
    if not config.get("automatic_payouts", False):
        return
    rows = await db.fetchall("""SELECT id FROM satshole.competitions WHERE status IN
('CLOSED','PAYING') ORDER BY ends_at LIMIT 10""")
    for row in rows:
        try:
            await settle(row["id"], send=True, automatic=True)
        except HTTPException:
            continue
    await prepare_refunds()
    rows = await db.fetchall("""SELECT id FROM satshole.outgoing WHERE kind='REFUND' AND
status!='PAID' AND held=0 LIMIT 20""")
    for row in rows:
        await transfer(row["id"], automatic=True)


async def operations():
    await prepare_refunds()
    return {
        "competitions": [
            dict(r)
            for r in await db.fetchall(
                """SELECT id,status,ends_at FROM satshole.competitions ORDER BY ends_at
DESC LIMIT 52"""
            )
        ],
        "payments": [
            dict(r)
            for r in await db.fetchall(
                """SELECT id,kind,competition_id,address,amount,status,error,held,
send_started_at,payment_hash FROM
satshole.outgoing ORDER BY created_at DESC LIMIT 100"""
            )
        ],
    }
