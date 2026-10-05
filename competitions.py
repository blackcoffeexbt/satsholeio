"""Weekly unique-player rankings and append-only receipt allocation.

Cutoff policy: receipt must be confirmed by this extension while the competition
is OPEN, strictly before ends_at. Late receipts remain refundable liabilities.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from lnbits.core.crud import get_payments, get_standalone_payment
from lnbits.core.models import PaymentFilters
from lnbits.core.services import create_invoice
from lnbits.db import Filter, Filters

from . import game_service as game
from .crud import db

DEFAULTS = {
    "leaderboard_enabled": False,
    "leaderboard_price": 250,
    "prize_percentage": 80,
    "first_percentage": 70,
    "second_percentage": 20,
    "third_percentage": 10,
    "allow_free_entries": False,
    "timezone": "Europe/London",
    "close_weekday": 6,
    "close_hour": 21,
    "close_minute": 0,
}


def week_bounds(stamp, config):
    zone = ZoneInfo(config["timezone"])
    local = datetime.fromtimestamp(stamp, timezone.utc).astimezone(zone)
    days = (config["close_weekday"] - local.weekday()) % 7
    end = (local + timedelta(days=days)).replace(
        hour=config["close_hour"],
        minute=config["close_minute"],
        second=0,
        microsecond=0,
    )
    if end.timestamp() <= stamp:
        end += timedelta(days=7)
    return int((end - timedelta(days=7)).timestamp()), int(end.timestamp())


def payout_address(value):
    value = value.strip().lower()
    if len(value) > 320 or value.count("@") != 1:
        raise HTTPException(422, "Enter a Lightning Address such as name@example.com.")
    name, domain = value.split("@")
    if not re.fullmatch(r"[a-z0-9._+\-]{1,64}", name) or not re.fullmatch(
        r"(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain
    ):
        raise HTTPException(422, "Enter a valid Lightning Address.")
    if domain.endswith((".localhost", ".local", ".internal")):
        raise HTTPException(422, "Use a public Lightning Address.")
    return value


def prizes(pot, config):
    # All three shares sum exactly to the liability; leftover integer sats go first.
    second = pot * config["second_percentage"] // 100
    third = pot * config["third_percentage"] // 100
    return [pot - second - third, second, third]


async def current_competition():
    settings = await game.settings_record()
    if not settings:
        return None
    config = {**DEFAULTS, **await game.game_config()}
    stamp = game.now()
    async with db.connect() as conn:
        await conn.execute(
            """UPDATE satshole.competitions SET status='CLOSED'
            WHERE status='OPEN' AND ends_at<=:time""",
            {"time": stamp},
        )
        row = await conn.fetchone(
            """SELECT * FROM satshole.competitions
            WHERE status='OPEN' AND ends_at>:time ORDER BY ends_at LIMIT 1""",
            {"time": stamp},
        )
        if row:
            return dict(row)
        start, end = week_bounds(stamp, config)
        data = {
            "id": str(uuid4()),
            "start": start,
            "end": end,
            "config": json.dumps(config),
            "wallet": settings["wallet_id"],
        }
        await conn.execute(
            """INSERT INTO satshole.competitions
            (id,starts_at,ends_at,status,config,wallet_id)
            VALUES (:id,:start,:end,'OPEN',:config,:wallet)
            ON CONFLICT (ends_at) DO NOTHING""",
            data,
        )
        return dict(
            await conn.fetchone(
                "SELECT * FROM satshole.competitions WHERE ends_at=:end", {"end": end}
            )
        )


async def competition_by_id(competition_id):
    row = await db.fetchone(
        "SELECT * FROM satshole.competitions WHERE id=:id", {"id": competition_id}
    )
    if not row:
        raise HTTPException(404, "Competition not found.")
    return dict(row)


async def ranking(competition_id):
    return [
        dict(row)
        for row in await db.fetchall(
            """SELECT * FROM ( SELECT
        s.player_id,s.display_name,r.authoritative_score AS score,
        e.seq,ROW_NUMBER() OVER (PARTITION BY s.player_id ORDER BY
        r.authoritative_score DESC,e.seq ASC) AS best FROM
        satshole.competition_events e JOIN satshole.submissions s ON
        s.id=e.submission_id JOIN satshole.runs r ON r.id=s.run_id JOIN
        satshole.players p ON p.id=s.player_id WHERE e.competition_id=:id AND
        e.kind='ENTRY_RECEIPT' AND s.status='ENTRY_CREATED' AND
        r.status='VERIFIED' AND p.blocked=0 ) ranked WHERE best=1 ORDER BY
        score DESC,seq ASC""",
            {"id": competition_id},
        )
    ]


async def totals(competition_id=None):
    clause = "WHERE competition_id=:id" if competition_id else ""
    row = await db.fetchone(
        f"""SELECT
        COALESCE(SUM(prize_contribution),0) AS prize_liability,
        COALESCE(SUM(operator_contribution),0) AS operator_revenue,
        COALESCE(SUM(refund_liability),0) AS refund_liability,
        COUNT(*) AS paid_receipts
        FROM satshole.competition_events {clause}""",
        {"id": competition_id} if competition_id else {},
    )
    result = dict(row)
    refund = await db.fetchone(
        f"""SELECT COALESCE(SUM(amount),0) AS amount,COUNT(*) AS n
        FROM satshole.entry_overpayments {clause}""",
        {"id": competition_id} if competition_id else {},
    )
    result["refund_liability"] += refund["amount"]
    result["paid_receipts"] += refund["n"]
    return result


async def public_board(competition_id=None):
    current = await current_competition()
    competition = await competition_by_id(competition_id) if competition_id else current
    if not competition:
        return {
            "competition": None,
            "pot": 0,
            "rankings": [],
            "paid_submissions": 0,
            "unique_entrants": 0,
        }
    config = json.loads(competition["config"])
    accounting = await totals(competition["id"])
    ranked = await ranking(competition["id"])
    amounts = prizes(accounting["prize_liability"], config)
    entries = await db.fetchone(
        """SELECT COUNT(*) AS n FROM satshole.competition_events
        WHERE competition_id=:id AND kind='ENTRY_RECEIPT'""",
        {"id": competition["id"]},
    )
    return {
        "competition": {
            k: competition[k] for k in ("id", "starts_at", "ends_at", "status")
        },
        "timezone": config["timezone"],
        "pot": accounting["prize_liability"],
        "paid_submissions": entries["n"],
        "unique_entrants": len(ranked),
        "prizes": amounts,
        "entry_price": config["leaderboard_price"],
        "entries_enabled": bool((await game.game_config())["leaderboard_enabled"]),
        "rankings": [
            {
                "position": i + 1,
                "display_name": r["display_name"],
                "score": r["score"],
                "estimated_prize": amounts[i] if i < 3 else 0,
            }
            for i, r in enumerate(ranked[:100])
        ],
    }


async def preview(run_id, player):
    run = await game.owned_run(run_id, player)
    current = await current_competition()
    board = await public_board()
    if not current:
        return {"eligible": False, "reason": "Game not configured.", "board": board}
    config = json.loads(current["config"])
    reason = None
    if run["status"] != "VERIFIED":
        reason = "This run must be verified first."
    elif run["competition_id"] != current["id"]:
        reason = "This run belongs to a previous competition. Play a new run."
    elif not run["paid"] and not config["allow_free_entries"]:
        reason = "Only paid runs can enter the cash leaderboard."
    ranked = await ranking(current["id"])
    existing = next(
        (i + 1 for i, r in enumerate(ranked) if r["player_id"] == player["id"]), None
    )
    score = run["authoritative_score"] or 0
    own = next((r for r in ranked if r["player_id"] == player["id"]), None)
    position = (
        existing
        if own and own["score"] >= score
        else 1
        + sum(r["score"] >= score for r in ranked if r["player_id"] != player["id"])
    )
    amounts = board["prizes"]
    return {
        "eligible": reason is None,
        "reason": reason,
        "would_rank": position,
        "current_position": existing,
        "top_three_threshold": ranked[2]["score"] if len(ranked) >= 3 else 0,
        "estimated_prize": amounts[position - 1] if position <= 3 else 0,
        "board": board,
    }


async def create_submission(run_id, player, address):
    check = await preview(run_id, player)
    if not check["eligible"]:
        raise HTTPException(409, check["reason"])
    if not (await game.game_config())["leaderboard_enabled"]:
        raise HTTPException(503, "Leaderboard entries are paused.")
    address = payout_address(address)
    current = await current_competition()
    run = await game.owned_run(run_id, player)
    if run["competition_id"] != current["id"] or game.now() >= current["ends_at"]:
        raise HTTPException(409, "This run belongs to a competition that has closed.")
    config = json.loads(current["config"])
    row = await db.fetchone(
        "SELECT * FROM satshole.submissions WHERE run_id=:id", {"id": run_id}
    )
    if row:
        return await entry_invoice(dict(row))
    stamp = game.now()
    amount = config["leaderboard_price"]
    share = amount * config["prize_percentage"] // 100
    data = {
        "id": str(uuid4()),
        "competition": current["id"],
        "player": player["id"],
        "run": run_id,
        "wallet": current["wallet_id"],
        "address": address,
        "name": player["display_name"],
        "amount": amount,
        "prize": share,
        "operator": amount - share,
        "time": stamp,
        "expiry": min(stamp + config["invoice_expiry"], current["ends_at"]),
    }
    async with db.connect() as conn:
        count = await conn.fetchone(
            """SELECT COUNT(*) AS n FROM satshole.submissions
            WHERE player_id=:player AND created_at>:time""",
            {"player": player["id"], "time": stamp - 60},
        )
        if count["n"] >= 5:
            raise HTTPException(429, "Too many entry invoice requests. Wait a minute.")
        # Recheck under the database lock; run_id is a database uniqueness boundary.
        row = await conn.fetchone(
            "SELECT * FROM satshole.submissions WHERE run_id=:id", {"id": run_id}
        )
        if row:
            submission_id = row["id"]
        else:
            await conn.execute(
                """INSERT INTO satshole.submissions
                (id,competition_id,player_id,run_id,wallet_id,payout_address,
                display_name,amount,prize_contribution,operator_contribution,
                status,created_at,expires_at)
                VALUES (:id,:competition,:player,:run,:wallet,:address,:name,
                :amount,:prize,:operator,'CREATED',:time,:expiry)""",
                data,
            )
            submission_id = data["id"]
    return await entry_invoice(
        dict(
            await db.fetchone(
                "SELECT * FROM satshole.submissions WHERE id=:id", {"id": submission_id}
            )
        )
    )


async def entry_invoice(row):
    current = await reconcile_submission(row)
    if current["status"] in ("ENTRY_CREATED", "REFUND_PENDING"):
        return current
    stamp = game.now()
    comp = await competition_by_id(row["competition_id"])
    config = json.loads(comp["config"])
    if stamp >= comp["ends_at"] or comp["status"] != "OPEN":
        raise HTTPException(409, "This competition has closed.")
    async with db.connect() as conn:
        active = await conn.fetchone(
            """SELECT * FROM satshole.entry_invoices WHERE submission_id=:id AND
        status IN ('CREATED','INVOICING','PENDING') AND expires_at>:time ORDER
        BY created_at DESC LIMIT 1""",
            {"id": row["id"], "time": stamp},
        )
        if active and active["status"] in ("PENDING", "INVOICING"):
            return current
        if active:
            invoice_id = active["id"]
            expiry = active["expires_at"]
        else:
            recent = await conn.fetchone(
                """SELECT COUNT(*) AS n FROM satshole.entry_invoices i
                JOIN satshole.submissions s ON s.id=i.submission_id
                WHERE s.player_id=:player AND i.created_at>:time""",
                {"player": row["player_id"], "time": stamp - 60},
            )
            if recent["n"] >= 5:
                raise HTTPException(
                    429, "Too many entry invoice requests. Wait a minute."
                )
            total = await conn.fetchone(
                "SELECT COUNT(*) AS n FROM satshole.entry_invoices "
                "WHERE submission_id=:id",
                {"id": row["id"]},
            )
            if total["n"] >= 10:
                raise HTTPException(
                    429, "Entry invoice retry limit reached. Contact the operator."
                )
            invoice_id = str(uuid4())
            expiry = min(stamp + config["invoice_expiry"], comp["ends_at"])
            await conn.execute(
                """INSERT INTO satshole.entry_invoices
                (id,submission_id,status,created_at,expires_at)
                VALUES (:id,:submission,'CREATED',:time,:expiry)""",
                {
                    "id": invoice_id,
                    "submission": row["id"],
                    "time": stamp,
                    "expiry": expiry,
                },
            )
        await conn.execute(
            "UPDATE satshole.entry_invoices SET status='INVOICING' WHERE id=:id",
            {"id": invoice_id},
        )
    try:
        payment = await create_invoice(
            wallet_id=row["wallet_id"],
            amount=row["amount"],
            memo="SatsHole weekly leaderboard entry",
            expiry=max(1, expiry - stamp),
            extra={
                "tag": "satshole_entry",
                "submission_id": row["id"],
                "invoice_id": invoice_id,
            },
            external_id=invoice_id,
        )
        await db.execute(
            """UPDATE satshole.entry_invoices SET status='PENDING',
        payment_hash=:hash,bolt11=:bolt WHERE id=:id AND status='INVOICING'""",
            {"id": invoice_id, "hash": payment.payment_hash, "bolt": payment.bolt11},
        )
        await db.execute(
            """UPDATE satshole.submissions SET status='PENDING',payment_hash=:hash,
            bolt11=:bolt,expires_at=:expiry WHERE id=:id
            AND status NOT IN ('ENTRY_CREATED','REFUND_PENDING')""",
            {
                "id": row["id"],
                "hash": payment.payment_hash,
                "bolt": payment.bolt11,
                "expiry": expiry,
            },
        )
    except Exception:
        await db.execute(
            """UPDATE satshole.entry_invoices SET status='CREATED'
            WHERE id=:id AND status='INVOICING'""",
            {"id": invoice_id},
        )
        raise HTTPException(
            503, "Entry invoice unavailable. Retry this same run."
        ) from None
    fresh = dict(
        await db.fetchone(
            "SELECT * FROM satshole.submissions WHERE id=:id", {"id": row["id"]}
        )
    )
    return await reconcile_submission(fresh)


def public_submission(row):
    return {k: row[k] for k in ("id", "status", "amount", "bolt11", "expires_at")}


async def submission_for_player(submission_id, player):
    row = await db.fetchone(
        "SELECT * FROM satshole.submissions WHERE id=:id AND player_id=:player",
        {"id": submission_id, "player": player["id"]},
    )
    if not row:
        raise HTTPException(404, "Entry invoice not found.")
    return await reconcile_submission(dict(row))


async def reconcile_submission(row):
    attempts = await db.fetchall(
        """SELECT * FROM satshole.entry_invoices WHERE submission_id=:id
        AND status IN ('CREATED','INVOICING','PENDING','EXPIRED','PAID')
        ORDER BY created_at DESC LIMIT 100""",
        {"id": row["id"]},
    )
    for attempt in attempts:
        if attempt["status"] == "PAID" and attempt["payment_hash"]:
            recorded = await db.fetchone(
                "SELECT id FROM satshole.competition_events WHERE payment_hash=:hash",
                {"hash": attempt["payment_hash"]},
            )
            overpaid = await db.fetchone(
                "SELECT payment_hash FROM satshole.entry_overpayments "
                "WHERE payment_hash=:hash",
                {"hash": attempt["payment_hash"]},
            )
            if recorded or overpaid:
                continue
        payment = None
        if attempt["payment_hash"]:
            payment = await get_standalone_payment(
                attempt["payment_hash"], incoming=True, wallet_id=row["wallet_id"]
            )
        else:
            matches = await get_payments(
                wallet_id=row["wallet_id"],
                incoming=True,
                complete=True,
                pending=True,
                filters=Filters(
                    model=PaymentFilters,
                    filters=[
                        Filter.parse_query(
                            "external_id", [attempt["id"]], PaymentFilters
                        )
                    ],
                ),
                limit=1,
            )
            payment = matches[0] if matches else None
            if (
                payment
                and payment.wallet_id == row["wallet_id"]
                and payment.amount == row["amount"] * 1000
            ):
                await db.execute(
                    """UPDATE satshole.entry_invoices SET payment_hash=:hash,
        bolt11=:bolt,status='PENDING' WHERE id=:id AND payment_hash IS NULL""",
                    {
                        "id": attempt["id"],
                        "hash": payment.payment_hash,
                        "bolt": payment.bolt11,
                    },
                )
                await db.execute(
                    """UPDATE satshole.submissions SET payment_hash=:hash,bolt11=:bolt,
                    status='PENDING',expires_at=:expiry WHERE id=:id
                    AND status NOT IN ('ENTRY_CREATED','REFUND_PENDING')""",
                    {
                        "id": row["id"],
                        "hash": payment.payment_hash,
                        "bolt": payment.bolt11,
                        "expiry": attempt["expires_at"],
                    },
                )
        if payment and payment.success:
            await record_entry_payment(payment)
        elif game.now() >= attempt["expires_at"]:
            await db.execute(
                """UPDATE satshole.entry_invoices SET status='EXPIRED' WHERE id=:id AND
        status='PENDING'""",
                {"id": attempt["id"]},
            )
    # Reconcile legacy entry invoices created before invoice-attempt tracking.
    if not attempts and row["payment_hash"] and row["status"] in ("PENDING", "EXPIRED"):
        payment = await get_standalone_payment(
            row["payment_hash"], incoming=True, wallet_id=row["wallet_id"]
        )
        if payment and payment.success:
            await record_entry_payment(payment)
    await db.execute(
        """UPDATE satshole.submissions SET status='EXPIRED'
        WHERE id=:id AND status='PENDING' AND expires_at<=:time""",
        {"id": row["id"], "time": game.now()},
    )
    return public_submission(
        dict(
            await db.fetchone(
                "SELECT * FROM satshole.submissions WHERE id=:id", {"id": row["id"]}
            )
        )
    )


async def record_entry_payment(payment):
    if payment.extra.get("tag") != "satshole_entry" or not payment.success:
        return
    async with db.connect() as conn:
        row = await conn.fetchone(
            "SELECT * FROM satshole.submissions WHERE payment_hash=:hash",
            {"hash": payment.payment_hash},
        )
        if not row and payment.extra.get("submission_id"):
            row = await conn.fetchone(
                "SELECT * FROM satshole.submissions " "WHERE id=:id",
                {"id": payment.extra["submission_id"]},
            )
        if (
            not row
            or payment.wallet_id != row["wallet_id"]
            or payment.amount != row["amount"] * 1000
        ):
            return
        if payment.extra.get("invoice_id"):
            attempt = await conn.fetchone(
                "SELECT * FROM satshole.entry_invoices "
                "WHERE id=:id AND submission_id=:sub",
                {"id": payment.extra["invoice_id"], "sub": row["id"]},
            )
            if not attempt:
                return
            await conn.execute(
                """UPDATE satshole.entry_invoices SET status='PAID',payment_hash=:hash,
        bolt11=:bolt WHERE id=:id AND (payment_hash IS NULL OR
        payment_hash=:hash)""",
                {
                    "id": attempt["id"],
                    "hash": payment.payment_hash,
                    "bolt": payment.bolt11,
                },
            )
        prior = await conn.fetchone(
            "SELECT * FROM satshole.competition_events WHERE submission_id=:id",
            {"id": row["id"]},
        )
        if prior and prior["payment_hash"] != payment.payment_hash:
            await conn.execute(
                """INSERT INTO satshole.entry_overpayments
        (payment_hash,competition_id,submission_id,player_id,run_id,amount,created_at)
        VALUES (:hash,:competition,:submission,:player,:run,:amount,:time) ON
        CONFLICT (payment_hash) DO NOTHING""",
                {
                    "hash": payment.payment_hash,
                    "competition": row["competition_id"],
                    "submission": row["id"],
                    "player": row["player_id"],
                    "run": row["run_id"],
                    "amount": row["amount"],
                    "time": game.now(),
                },
            )
            return
        await conn.execute(
            """UPDATE satshole.submissions SET payment_hash=:hash,bolt11=:bolt
            WHERE id=:id AND payment_hash IS NULL""",
            {"id": row["id"], "hash": payment.payment_hash, "bolt": payment.bolt11},
        )
        stamp = game.now()
        comp = await conn.fetchone(
            "SELECT * FROM satshole.competitions WHERE id=:id",
            {"id": row["competition_id"]},
        )
        eligible = bool(comp and comp["status"] == "OPEN" and stamp < comp["ends_at"])
        data = {
            "id": "entry:" + payment.payment_hash,
            "kind": "ENTRY_RECEIPT" if eligible else "LATE_RECEIPT",
            "competition": row["competition_id"],
            "submission": row["id"],
            "player": row["player_id"],
            "run": row["run_id"],
            "hash": payment.payment_hash,
            "amount": row["amount"],
            "prize": row["prize_contribution"] if eligible else 0,
            "operator": row["operator_contribution"] if eligible else 0,
            "refund": 0 if eligible else row["amount"],
            "time": stamp,
        }
        # One append-only insert records the receipt and both allocations.
        await conn.execute(
            """INSERT INTO satshole.competition_events
        (id,kind,competition_id,submission_id,player_id,run_id,payment_hash,
        amount,prize_contribution,operator_contribution,refund_liability,created_at)
        VALUES (:id,:kind,:competition,:submission,:player,:run,:hash,
        :amount,:prize,:operator,:refund,:time) ON CONFLICT (id) DO NOTHING""",
            data,
        )
        event = await conn.fetchone(
            "SELECT kind FROM satshole.competition_events WHERE id=:id",
            {"id": data["id"]},
        )
        await conn.execute(
            "UPDATE satshole.submissions SET status=:status WHERE id=:id",
            {
                "id": row["id"],
                "status": (
                    "ENTRY_CREATED"
                    if event["kind"] == "ENTRY_RECEIPT"
                    else "REFUND_PENDING"
                ),
            },
        )


async def history():
    return [dict(r) for r in await db.fetchall("""SELECT id,starts_at,ends_at,status
        FROM satshole.competitions ORDER BY ends_at DESC LIMIT 52""")]
