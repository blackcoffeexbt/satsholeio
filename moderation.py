"""Reasoned, wallet-authenticated operator actions with a recoverable audit journal."""

import json

from fastapi import HTTPException
from lnbits.core.services.payments import check_payment_status

from . import competitions as comp
from . import game_service as game
from . import settlement
from .crud import db


async def apply_event(event):
    payload = json.loads(event["payload"])
    target = event["target_id"]
    if event["kind"] == "PLAYER_BLOCK":
        await db.execute(
            "UPDATE satshole.players SET blocked=:state WHERE id=:id",
            {"id": target, "state": payload["blocked"]},
        )
    elif event["kind"] == "ENTRY_REVIEW":
        await db.execute(
            "UPDATE satshole.submissions SET disqualified=:state WHERE id=:id",
            {"id": target, "state": payload["disqualified"]},
        )
        if payload.get("refund"):
            row = payload["refund"]
            await db.execute(
                """INSERT INTO satshole.admin_refunds
                (submission_id,competition_id,amount,prize_debit,operator_debit,outgoing_id)
                VALUES (:submission,:competition,:amount,:prize,:operator,:outgoing)
                ON CONFLICT (submission_id) DO NOTHING""",
                row,
            )
            await settlement.obligation(
                row["outgoing"],
                "REFUND",
                row["competition"],
                row["wallet"],
                row["address"],
                row["amount"],
            )
    elif event["kind"] == "PAYMENT_HOLD":
        await db.execute(
            "UPDATE satshole.outgoing SET held=:held WHERE id=:id",
            {"id": target, "held": payload["held"]},
        )
    elif event["kind"] == "PAYMENT_REPAIR":
        await db.execute(
            """UPDATE satshole.outgoing SET address=:address,
            bolt11=NULL,payment_hash=NULL,send_started_at=NULL,status='READY',
            error=NULL,held=1 WHERE id=:id""",
            {"id": target, "address": payload["address"]},
        )
    elif event["kind"] == "EMERGENCY_PAUSE":
        await db.execute(
            "UPDATE satshole.game_settings SET config=:config WHERE id='game'",
            {"config": json.dumps(payload["config"])},
        )
    elif event["kind"] == "OPERATION":
        pass  # Requested action; native receipts record the payment outcome.
    else:
        raise ValueError("Unknown operator action")
    await db.execute(
        """INSERT INTO satshole.operator_applied (event_id,applied_at)
        VALUES (:id,:time) ON CONFLICT (event_id) DO NOTHING""",
        {"id": event["id"], "time": game.now()},
    )


async def recover_unlocked():
    # The journal commits before its projection; replay pending events in order.
    events = await db.fetchall("""SELECT e.* FROM satshole.operator_events e
        LEFT JOIN satshole.operator_applied a ON a.event_id=e.id
        WHERE a.event_id IS NULL ORDER BY e.seq""")
    for event in events:
        await apply_event(dict(event))


async def recover():
    async with settlement._lock:
        await recover_unlocked()


async def existing(request_id, actor, kind, target, reason, intent):
    row = await db.fetchone(
        "SELECT * FROM satshole.operator_events WHERE id=:id", {"id": request_id}
    )
    if not row:
        return None
    payload = json.loads(row["payload"])
    if (
        row["actor_id"],
        row["kind"],
        row["target_id"],
        row["reason"],
        payload["intent"],
    ) != (actor, kind, target, reason, intent):
        raise HTTPException(409, "This action ID was used for a different request.")
    return {"event_id": request_id, "applied": True}


async def journal(request_id, actor, kind, target, reason, intent, payload):
    payload["intent"] = intent
    event = {
        "id": request_id,
        "actor_id": actor,
        "kind": kind,
        "target_id": target,
        "reason": reason,
        "payload": json.dumps(payload),
        "created_at": game.now(),
    }
    await db.execute(
        """INSERT INTO satshole.operator_events
        (id,actor_id,kind,target_id,reason,payload,created_at)
        VALUES (:id,:actor_id,:kind,:target_id,:reason,:payload,:created_at)""",
        event,
    )
    await apply_event(event)
    return {"event_id": request_id, "applied": True}


async def block_player(target, blocked, actor, reason, request_id):
    async with settlement._lock:
        await recover_unlocked()
        old = await existing(request_id, actor, "PLAYER_BLOCK", target, reason, blocked)
        if old:
            return old
        player = await db.fetchone(
            "SELECT blocked FROM satshole.players WHERE id=:id", {"id": target}
        )
        if not player:
            raise HTTPException(404, "Player not found.")
        return await journal(
            request_id,
            actor,
            "PLAYER_BLOCK",
            target,
            reason,
            blocked,
            {"blocked": int(blocked), "before": player["blocked"]},
        )


async def review_entry(target, disqualified, refund, actor, reason, request_id):
    intent = {"disqualified": disqualified, "refund": refund}
    async with settlement._lock:
        await recover_unlocked()
        old = await existing(request_id, actor, "ENTRY_REVIEW", target, reason, intent)
        if old:
            return old
        row = await db.fetchone(
            """SELECT s.* FROM satshole.submissions s JOIN
            satshole.competition_events e ON e.submission_id=s.id
            WHERE s.id=:id AND e.kind='ENTRY_RECEIPT'""",
            {"id": target},
        )
        if not row:
            raise HTTPException(404, "Paid leaderboard entry not found.")
        frozen = await db.fetchone(
            "SELECT competition_id FROM satshole.settlements WHERE competition_id=:id",
            {"id": row["competition_id"]},
        )
        if frozen:
            raise HTTPException(
                409,
                "Settlement is frozen. This entry and its allocation cannot change.",
            )
        refunded = await db.fetchone(
            "SELECT submission_id FROM satshole.admin_refunds WHERE submission_id=:id",
            {"id": target},
        )
        if not disqualified and (refund or refunded):
            raise HTTPException(409, "A refunded entry cannot be restored.")
        payload = {"before": row["disqualified"], "disqualified": int(disqualified)}
        if refund and not refunded:
            payload["refund"] = {
                "submission": target,
                "competition": row["competition_id"],
                "amount": row["amount"],
                "prize": row["prize_contribution"],
                "operator": row["operator_contribution"],
                "outgoing": "admin-refund:" + target,
                "wallet": row["wallet_id"],
                "address": row["payout_address"],
            }
        return await journal(
            request_id, actor, "ENTRY_REVIEW", target, reason, intent, payload
        )


async def hold_payment(target, held, actor, reason, request_id):
    async with settlement._lock:
        await recover_unlocked()
        old = await existing(request_id, actor, "PAYMENT_HOLD", target, reason, held)
        if old:
            return old
        row = await db.fetchone(
            "SELECT held,status FROM satshole.outgoing WHERE id=:id", {"id": target}
        )
        if not row:
            raise HTTPException(404, "Payment not found.")
        if row["status"] == "PAID":
            raise HTTPException(409, "Completed payments cannot be changed.")
        return await journal(
            request_id,
            actor,
            "PAYMENT_HOLD",
            target,
            reason,
            held,
            {"held": int(held), "before": row["held"]},
        )


async def repair_payment(target, address, actor, reason, request_id):
    address = comp.payout_address(address)
    async with settlement._lock:
        await recover_unlocked()
        old = await existing(
            request_id, actor, "PAYMENT_REPAIR", target, reason, address
        )
        if old:
            return old
        row = await db.fetchone(
            "SELECT * FROM satshole.outgoing WHERE id=:id", {"id": target}
        )
        if not row:
            raise HTTPException(404, "Payment not found.")
        row = dict(row)
        receipt = await db.fetchone(
            "SELECT outgoing_id FROM satshole.outgoing_receipts WHERE outgoing_id=:id",
            {"id": target},
        )
        if row["status"] == "PAID" or receipt:
            raise HTTPException(409, "Completed payments cannot be repaired.")
        proof = "Never sent"
        if row["payment_hash"]:
            native = await settlement.get_standalone_payment(
                row["payment_hash"], incoming=False
            )
            if native:
                if (
                    native.wallet_id != row["wallet_id"]
                    or abs(native.amount) != row["amount"] * 1000
                ):
                    raise HTTPException(409, "Native payment ownership mismatch.")
                if native.success:
                    await settlement.confirm_outgoing(row, native)
                    raise HTTPException(
                        409, "Payment has completed; no repair is needed."
                    )
                if native.pending or not native.failed:
                    raise HTTPException(
                        409,
                        "Pending or uncertain sends cannot use a replacement invoice.",
                    )
                decoded = settlement.decode(row["bolt11"])
                if decoded.expiry_date > game.now():
                    raise HTTPException(
                        409,
                        "Wait for the failed invoice to expire before replacing it.",
                    )
                # Recheck the funding source, not only the saved local failure state.
                status = await check_payment_status(native)
                if not status.failed:
                    raise HTTPException(
                        409, "The funding source has not confirmed a final failure."
                    )
                proof = (
                    "Expired invoice; native record and funding source confirm failure"
                )
            elif row["send_started_at"] is not None:
                raise HTTPException(
                    409, "Send outcome is unknown. Reconcile the saved invoice first."
                )
            elif row["status"] not in ("READY", "RETRY"):
                # Older rows lack send_started_at; remain conservative.
                raise HTTPException(
                    409, "Send outcome is unknown. Reconcile the saved invoice first."
                )
        elif row["send_started_at"] is not None:
            raise HTTPException(409, "Incomplete send record requires reconciliation.")
        return await journal(
            request_id,
            actor,
            "PAYMENT_REPAIR",
            target,
            reason,
            address,
            {
                "address": address,
                "before": {
                    k: row[k]
                    for k in (
                        "address",
                        "payment_hash",
                        "bolt11",
                        "send_started_at",
                        "status",
                    )
                },
                "proof": proof,
            },
        )


async def emergency_pause(actor, reason, request_id):
    async with settlement._lock:
        await recover_unlocked()
        old = await existing(request_id, actor, "EMERGENCY_PAUSE", "game", reason, True)
        if old:
            return old
        config = await game.game_config()
        before = {
            k: config[k]
            for k in ("enabled", "leaderboard_enabled", "automatic_payouts")
        }
        config.update(enabled=False, leaderboard_enabled=False, automatic_payouts=False)
        return await journal(
            request_id,
            actor,
            "EMERGENCY_PAUSE",
            "game",
            reason,
            True,
            {"before": before, "config": config},
        )


async def record_operation(target, actor, reason, request_id):
    async with settlement._lock:
        await recover_unlocked()
        old = await existing(request_id, actor, "OPERATION", target, reason, target)
        if old:
            return old
        return await journal(
            request_id,
            actor,
            "OPERATION",
            target,
            reason,
            target,
            {"requested": target},
        )


async def inspect(competition_id=None, page=0):
    await recover()
    parameters = {"offset": page * 50}
    clause = ""
    if competition_id:
        await comp.competition_by_id(competition_id)
        clause = " WHERE r.competition_id=:competition"
        parameters["competition"] = competition_id
    runs = await db.fetchall(
        """SELECT r.id,r.player_id,p.display_name,p.blocked,
        r.status,r.paid,r.amount,r.competition_id,r.created_at,r.authoritative_score,
        r.game_version,r.map_version,r.input_hash,r.seed,r.started_at,r.finished_at,
        r.config,r.result,CASE WHEN r.input_log IS NULL THEN 0 ELSE 1 END
        AS has_input_log,
        s.id AS submission_id,s.status AS entry_status,
        s.disqualified FROM satshole.runs r JOIN satshole.players p ON p.id=r.player_id
        LEFT JOIN satshole.submissions s ON s.run_id=r.id"""
        + clause
        + " ORDER BY r.created_at DESC,r.id LIMIT 50 OFFSET :offset",
        parameters,
    )
    reviewed = []
    private_fields = ("input_hash", "seed", "config", "result", "has_input_log")
    for raw in runs:
        item = dict(raw)
        item["flags"] = await run_flags(item)
        for key in private_fields:
            item.pop(key)
        reviewed.append(item)
    audit = await db.fetchall("""SELECT e.id,e.actor_id,e.kind,e.target_id,e.reason,
        e.created_at,CASE WHEN a.event_id IS NULL THEN 0 ELSE 1 END AS applied
        FROM satshole.operator_events e LEFT JOIN satshole.operator_applied a
        ON a.event_id=e.id ORDER BY e.seq DESC LIMIT 100""")
    return {
        "runs": reviewed,
        "audit": [dict(e) for e in audit],
        "page": page,
    }


async def inspect_run(run_id):
    row = await db.fetchone("SELECT * FROM satshole.runs WHERE id=:id", {"id": run_id})
    if not row:
        raise HTTPException(404, "Run not found.")
    fields = (
        "id",
        "player_id",
        "status",
        "paid",
        "amount",
        "competition_id",
        "created_at",
        "started_at",
        "finished_at",
        "verified_at",
        "authoritative_score",
        "game_version",
        "map_version",
        "input_hash",
    )
    result = {key: row[key] for key in fields}
    result["config"] = json.loads(row["config"])
    result["verification"] = json.loads(row["result"]) if row["result"] else None
    result["replay_available"] = row["input_log"] is not None
    return result


async def replay_payload(run_id):
    row = await db.fetchone("SELECT * FROM satshole.runs WHERE id=:id", {"id": run_id})
    if not row or row["input_log"] is None:
        raise HTTPException(404, "Committed replay not available.")
    return {
        "version": row["game_version"],
        "map": row["map_version"],
        "seed": row["seed"],
        "config": json.loads(row["config"]),
        "inputs": json.loads(row["input_log"]),
    }


async def run_flags(row):
    flags = []
    if row["status"] == "INVALID":
        flags.append("Replay verification rejected")
    if row["status"] == "VERIFIED":
        if not row["input_hash"] or not row["has_input_log"] or not row["result"]:
            flags.append("Verified record lacks replay commitment")
        if row["result"]:
            try:
                if json.loads(row["result"])["score"] != row["authoritative_score"]:
                    flags.append("Stored score differs from replay result")
            except (ValueError, KeyError, TypeError):
                flags.append("Stored replay result is unreadable")
        if row["started_at"] is not None and row["finished_at"] is not None:
            duration = json.loads(row["config"])["duration"]
            if row["finished_at"] < row["started_at"] + duration - 1:
                flags.append("Finish recorded before run duration elapsed")
        if row["input_hash"]:
            duplicate = await db.fetchone(
                """SELECT COUNT(*) AS n FROM satshole.runs
                WHERE input_hash=:hash AND seed=:seed AND game_version=:version
                AND map_version=:map AND player_id!=:player AND status='VERIFIED'""",
                {
                    "hash": row["input_hash"],
                    "seed": row["seed"],
                    "version": row["game_version"],
                    "map": row["map_version"],
                    "player": row["player_id"],
                },
            )
            if duplicate["n"]:
                flags.append("Same seed and input commitment used by another player")
    invalid = await db.fetchone(
        """SELECT COUNT(*) AS n FROM satshole.runs
        WHERE player_id=:id AND status='INVALID' AND created_at>=:since""",
        {"id": row["player_id"], "since": game.now() - 86400},
    )
    if invalid["n"] >= 3:
        flags.append("Player has three or more rejected replays in 24 hours")
    return flags
