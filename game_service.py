"""Server-owned single-use attempts. Financial records use unique payment hashes."""

import hashlib
import json
import secrets
import time
import unicodedata
from uuid import uuid4

from fastapi import HTTPException
from lnbits.core.crud import get_payments, get_standalone_payment
from lnbits.core.models import PaymentFilters
from lnbits.core.services import create_invoice
from lnbits.db import Filter, Filters

from .crud import db
from .replay import MAP_VERSION, VERSION, verify

DEFAULTS = {
    "automatic_payouts": False,
    "settlement_delay": 3600,
    "undistributed_policy": "carry",
    "enabled": True,
    "game_price": 25,
    "free_runs": 3,
    "duration": 120,
    "ai_count": 8,
    "competitor_aggression": 5,
    "death_penalty": 20,
    "invoice_expiry": 600,
    "ready_expiry": 3600,
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


def now():
    return int(time.time())


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def clean_name(value):
    value = value.strip()
    if not 1 <= len(value) <= 24 or any(
        unicodedata.category(c).startswith("C") or c in "<>&" for c in value
    ):
        raise HTTPException(
            422, "Use 1-24 characters without markup or control characters."
        )
    return value


async def settings_record():
    row = await db.fetchone("SELECT * FROM satshole.game_settings WHERE id = 'game'")
    return dict(row) if row else None


async def game_config():
    row = await settings_record()
    return (
        {**DEFAULTS, **json.loads(row["config"])}
        if row
        else {**DEFAULTS, "enabled": False}
    )


async def player_for_token(token):
    if not token or len(token) > 100:
        raise HTTPException(401, "Player session required.")
    p = await db.fetchone(
        "SELECT * FROM satshole.players WHERE token_hash = :hash",
        {"hash": digest(token)},
    )
    if not p:
        raise HTTPException(401, "Player session expired.")
    if p["blocked"]:
        raise HTTPException(403, "Player is blocked.")
    return dict(p)


async def new_player(name):
    token = secrets.token_urlsafe(32)
    player = {
        "id": str(uuid4()),
        "token_hash": digest(token),
        "display_name": clean_name(name),
        "created_at": now(),
    }
    await db.execute(
        """INSERT INTO satshole.players (id,token_hash,display_name,created_at)
        VALUES (:id,:token_hash,:display_name,:created_at)""",
        player,
    )
    return token, await player_for_token(token)


async def owned_run(run_id, player):
    row = await db.fetchone(
        "SELECT * FROM satshole.runs WHERE id=:id AND player_id=:player",
        {"id": run_id, "player": player["id"]},
    )
    if not row:
        raise HTTPException(404, "Run not found.")
    return dict(row)


def public_run(run):
    return {
        key: run[key]
        for key in (
            "id",
            "status",
            "paid",
            "amount",
            "bolt11",
            "expires_at",
            "authoritative_score",
            "game_version",
            "map_version",
        )
    }


async def reconcile(run):
    if not run["payment_hash"] and run["amount"] > 0:
        matches = await get_payments(
            wallet_id=run["wallet_id"],
            incoming=True,
            complete=True,
            pending=True,
            filters=Filters(
                model=PaymentFilters,
                filters=[
                    Filter.parse_query("external_id", [run["id"]], PaymentFilters)
                ],
            ),
            limit=1,
        )
        if matches:
            payment = matches[0]
            if (
                payment.wallet_id == run["wallet_id"]
                and payment.amount == run["amount"] * 1000
            ):
                await db.execute(
                    """UPDATE satshole.runs SET payment_hash=:hash,bolt11=:bolt,
        status='WAITING_PAYMENT' WHERE id=:id AND payment_hash IS NULL AND
        status IN ('CREATING','INVALID')""",
                    {
                        "id": run["id"],
                        "hash": payment.payment_hash,
                        "bolt": payment.bolt11,
                    },
                )
                run = dict(
                    await db.fetchone(
                        "SELECT * FROM satshole.runs WHERE id=:id", {"id": run["id"]}
                    )
                )
    if run["payment_hash"] and run["status"] in ("WAITING_PAYMENT", "EXPIRED"):
        payment = await get_standalone_payment(
            run["payment_hash"], incoming=True, wallet_id=run["wallet_id"]
        )
        if payment and payment.success and payment.amount == run["amount"] * 1000:
            await record_payment(payment)
        elif run["expires_at"] <= now() and run["status"] == "WAITING_PAYMENT":
            await db.execute(
                """UPDATE satshole.runs SET status='EXPIRED' WHERE id=:id AND
        status='WAITING_PAYMENT'""",
                {"id": run["id"]},
            )
    if run["status"] == "READY" and run["expires_at"] <= now():
        await db.execute(
            "UPDATE satshole.runs SET status='EXPIRED' WHERE id=:id AND status='READY'",
            {"id": run["id"]},
        )
    return dict(
        await db.fetchone("SELECT * FROM satshole.runs WHERE id=:id", {"id": run["id"]})
    )


async def record_payment(payment):
    if payment.extra.get("tag") != "satshole_game" or not payment.success:
        return
    # Validate the stored receipt hash, wallet and exact amount.
    run = await db.fetchone(
        "SELECT * FROM satshole.runs WHERE payment_hash=:hash",
        {"hash": payment.payment_hash},
    )
    if not run and payment.extra.get("run_id"):
        # Recover a receipt delivered before its invoice hash was persisted.
        candidate = await db.fetchone(
            """SELECT * FROM satshole.runs WHERE id=:id
            AND payment_hash IS NULL AND status IN ('CREATING','INVALID')""",
            {"id": payment.extra["run_id"]},
        )
        if (
            candidate
            and payment.wallet_id == candidate["wallet_id"]
            and payment.amount == candidate["amount"] * 1000
        ):
            await db.execute(
                """UPDATE satshole.runs SET payment_hash=:hash,bolt11=:bolt,
        status='WAITING_PAYMENT' WHERE id=:id AND payment_hash IS NULL AND
        status IN ('CREATING','INVALID')""",
                {
                    "id": candidate["id"],
                    "hash": payment.payment_hash,
                    "bolt": payment.bolt11,
                },
            )
            run = await db.fetchone(
                "SELECT * FROM satshole.runs WHERE payment_hash=:hash",
                {"hash": payment.payment_hash},
            )
    if (
        not run
        or payment.wallet_id != run["wallet_id"]
        or payment.amount != run["amount"] * 1000
    ):
        return
    await db.execute(
        """INSERT INTO satshole.financial_events
        (id,kind,payment_hash,player_id,run_id,amount,created_at)
        VALUES (:id,'game_revenue',:hash,:player,:run,:amount,:time)
        ON CONFLICT (id) DO NOTHING""",
        {
            "id": "game:" + payment.payment_hash,
            "hash": payment.payment_hash,
            "player": run["player_id"],
            "run": run["id"],
            "amount": run["amount"],
            "time": now(),
        },
    )
    config = json.loads(run["config"])
    # Late valid payments grant the same single attempt rather than losing funds.
    await db.execute(
        """UPDATE satshole.runs SET status='READY', paid=1, expires_at=:expiry
        WHERE id=:id AND paid=0 AND status IN ('WAITING_PAYMENT','EXPIRED')""",
        {"id": run["id"], "expiry": now() + config["ready_expiry"]},
    )


async def create_run(player, free):
    record = await settings_record()
    config = await game_config()
    if not record or not config["enabled"]:
        raise HTTPException(
            503, "New games are paused. Ask the operator to configure the game."
        )
    from .competitions import current_competition

    competition = await current_competition()
    config = json.loads(competition["config"])
    async with db.connect() as conn:
        pending = await conn.fetchone(
            """SELECT COUNT(*) AS n FROM satshole.runs WHERE player_id=:player AND
        status IN ('CREATING','WAITING_PAYMENT','READY') AND expires_at>:time""",
            {"player": player["id"], "time": now()},
        )
        recent = await conn.fetchone(
            """SELECT COUNT(*) AS n FROM satshole.runs WHERE player_id=:player AND
        created_at>:time""",
            {"player": player["id"], "time": now() - 60},
        )
        if pending["n"] >= 3 or recent["n"] >= 6:
            raise HTTPException(
                429,
                "Too many run requests. Complete an existing attempt or wait a minute.",
            )
        if free:
            used = await conn.execute(
                """UPDATE satshole.players SET free_used=free_used+1
                WHERE id=:id AND free_used<:limit AND blocked=0""",
                {"id": player["id"], "limit": config["free_runs"]},
            )
            if used.rowcount != 1:
                raise HTTPException(409, "No introductory free games remain.")
        run = {
            "id": str(uuid4()),
            "competition": competition["id"],
            "player": player["id"],
            "wallet": record["wallet_id"],
            "status": "READY" if free else "CREATING",
            "amount": 0 if free else config["game_price"],
            "version": VERSION,
            "map": MAP_VERSION,
            "config": json.dumps(config),
            "seed": secrets.randbits(32),
            "time": now(),
            "expiry": now()
            + (config["ready_expiry"] if free else config["invoice_expiry"]),
        }
        try:
            await conn.execute(
                """INSERT INTO satshole.runs
        (id,player_id,competition_id,wallet_id,status,amount,game_version,map_version,config,seed,created_at,expires_at)
        VALUES
        (:id,:player,:competition,:wallet,:status,:amount,:version,:map,:config,:seed,:time,:expiry)""",
                run,
            )
        except Exception:
            if free:
                await conn.execute(
                    "UPDATE satshole.players SET free_used=free_used-1 WHERE id=:id",
                    {"id": player["id"]},
                )
            raise
    if not free:
        try:
            invoice = await create_invoice(
                wallet_id=record["wallet_id"],
                amount=run["amount"],
                memo="SatsHole · one city run",
                external_id=run["id"],
                expiry=config["invoice_expiry"],
                extra={"tag": "satshole_game", "run_id": run["id"]},
            )
            await db.execute(
                """UPDATE satshole.runs SET
        status='WAITING_PAYMENT',payment_hash=:hash,bolt11=:bolt WHERE id=:id
        AND status='CREATING'""",
                {"id": run["id"], "hash": invoice.payment_hash, "bolt": invoice.bolt11},
            )
        except Exception:
            await db.execute(
                "UPDATE satshole.runs SET status='INVALID' "
                "WHERE id=:id AND status='CREATING'",
                {"id": run["id"]},
            )
            raise HTTPException(
                503, "Could not create a game invoice. Try again later."
            ) from None
    return await reconcile(await owned_run(run["id"], player))


async def start_run(run_id, player):
    run = await reconcile(await owned_run(run_id, player))
    token = secrets.token_urlsafe(32)
    stamp = now()
    result = await db.execute(
        """UPDATE satshole.runs SET
        status='RUNNING',started_at=:time,token_hash=:token WHERE id=:id AND
        player_id=:player AND status='READY' AND expires_at>:time""",
        {"id": run_id, "player": player["id"], "time": stamp, "token": digest(token)},
    )
    if result.rowcount != 1:
        raise HTTPException(
            409, "This attempt is not available or has already started."
        )
    return {
        "id": run_id,
        "run_token": token,
        "seed": run["seed"],
        "game_version": run["game_version"],
        "map_version": run["map_version"],
        "config": json.loads(run["config"]),
    }


async def finished_result(run, player):
    best = await db.fetchone(
        """SELECT COALESCE(MAX(authoritative_score),0) AS score
        FROM satshole.runs WHERE player_id=:id AND status='VERIFIED'""",
        {"id": player["id"]},
    )
    return {**public_run(run), "personal_best": best["score"]}


async def finish_run(run_id, player, token, inputs):
    run = await owned_run(run_id, player)
    if not run["token_hash"] or not secrets.compare_digest(
        run["token_hash"], digest(token)
    ):
        raise HTTPException(403, "Invalid run token.")
    config = json.loads(run["config"])
    if not run["started_at"]:
        raise HTTPException(409, "This run has not started.")
    if now() < run["started_at"] + config["duration"] - 1:
        raise HTTPException(409, "The run has not reached its finish time.")
    payload = json.dumps(inputs, separators=(",", ":"))
    if len(payload) > 256_000:
        raise HTTPException(413, "Input log too large.")
    fingerprint = digest(payload)
    if run["input_hash"]:
        if fingerprint != run["input_hash"]:
            raise HTTPException(
                409, "A different result was already submitted for this attempt."
            )
        if run["status"] != "FINISHED_UNVERIFIED":
            return await finished_result(run, player)
    if now() > run["started_at"] + config["duration"] + 300:
        raise HTTPException(409, "The run submission window has expired.")
    claimed = await db.execute(
        """UPDATE satshole.runs SET
        status='VERIFYING',input_hash=:hash,input_log=:log,finished_at=:time
        WHERE id=:id AND ((status='RUNNING' AND input_hash IS NULL) OR
        (status='FINISHED_UNVERIFIED' AND input_hash=:hash))""",
        {"id": run_id, "hash": fingerprint, "log": payload, "time": now()},
    )
    if claimed.rowcount != 1:
        raise HTTPException(409, "Run is already being verified.")
    try:
        result = await verify({**run, "config": config}, inputs)
    except (ValueError, TimeoutError):
        await db.execute(
            "UPDATE satshole.runs SET status='INVALID' WHERE id=:id", {"id": run_id}
        )
        raise HTTPException(422, "Replay could not verify this input log.") from None
    except Exception:
        # Identical-payload retries can recover operational verifier failures.
        await db.execute(
            "UPDATE satshole.runs SET status='FINISHED_UNVERIFIED' WHERE id=:id",
            {"id": run_id},
        )
        raise HTTPException(503, "Verifier temporarily unavailable.") from None
    await db.execute(
        """UPDATE satshole.runs SET
        status='VERIFIED',authoritative_score=:score,result=:result,verified_at=:time
        WHERE id=:id AND status='VERIFYING'""",
        {
            "id": run_id,
            "score": result["score"],
            "result": json.dumps(result),
            "time": now(),
        },
    )
    return await finished_result(await owned_run(run_id, player), player)
