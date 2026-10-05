"""Public cookie-authenticated game API and wallet-owned operator configuration."""

import json
import time
from collections import deque
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from lnbits.core.crud import get_wallet
from lnbits.core.models import WalletTypeInfo
from lnbits.decorators import require_admin_key
from lnbits.settings import settings
from pydantic import (
    BaseModel,
    Field,
    StrictInt,
    ValidationError,
    root_validator,
    validator,
)

from . import competitions, moderation, settlement
from . import game_service as service
from .crud import db

router = APIRouter(prefix="/api/v1/game")
COOKIE = "satshole_player"
_buckets = {}


class StrictModel(BaseModel):
    class Config:
        extra = "forbid"


class Profile(StrictModel):
    display_name: str = "Visitor"


class RunRequest(StrictModel):
    free: bool = True


class FinishRequest(StrictModel):
    run_token: str = Field(min_length=30, max_length=100)
    inputs: list[tuple[StrictInt, StrictInt, StrictInt]] = Field(max_items=6000)


class GameSettings(StrictModel):
    enabled: bool = True
    game_price: int = Field(default=25, ge=1, le=100000)
    free_runs: int = Field(default=3, ge=0, le=100)
    duration: int = Field(default=120, ge=10, le=300)
    ai_count: int = Field(default=8, ge=0, le=16)
    competitor_aggression: int = Field(default=5, ge=1, le=10)
    death_penalty: int = Field(default=20, ge=0, le=100)
    invoice_expiry: int = Field(default=600, ge=60, le=3600)
    ready_expiry: int = Field(default=3600, ge=300, le=86400)
    undistributed_policy: Literal["carry", "hold"] = "carry"
    automatic_payouts: bool = False
    settlement_delay: int = Field(default=3600, ge=60, le=604800)
    leaderboard_enabled: bool = False
    leaderboard_price: int = Field(default=250, ge=1, le=1000000)
    prize_percentage: int = Field(default=80, ge=0, le=100)
    first_percentage: int = Field(default=70, ge=0, le=100)
    second_percentage: int = Field(default=20, ge=0, le=100)
    third_percentage: int = Field(default=10, ge=0, le=100)
    allow_free_entries: bool = False
    timezone: str = "Europe/London"
    close_weekday: int = Field(default=6, ge=0, le=6)
    close_hour: int = Field(default=21, ge=0, le=23)
    close_minute: int = Field(default=0, ge=0, le=59)

    @root_validator(skip_on_failure=True)
    def validate_competition(cls, values):
        if (
            sum(
                values[k]
                for k in ("first_percentage", "second_percentage", "third_percentage")
            )
            != 100
        ):
            raise ValueError("Winner percentages must total 100.")
        try:
            ZoneInfo(values["timezone"])
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Choose a valid IANA timezone.") from None
        return values


class EntryRequest(StrictModel):
    run_id: str = Field(min_length=1, max_length=50)
    lightning_address: str = Field(min_length=3, max_length=320)


class OperatorAction(StrictModel):
    request_id: UUID
    reason: str = Field(min_length=3, max_length=500)

    @validator("reason")
    def meaningful_reason(cls, value):
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Enter a reason for this operator action.")
        return value


class PlayerReview(OperatorAction):
    blocked: bool


class EntryReview(OperatorAction):
    disqualified: bool
    refund: bool = False


class PaymentHold(OperatorAction):
    held: bool


class PaymentRepair(OperatorAction):
    lightning_address: str = Field(min_length=3, max_length=320)


def guard(request: Request):
    if request.method not in ("GET", "HEAD"):
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Cross-origin game requests are not permitted.")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-site game requests are not permitted.")
    key = service.digest(request.client.host if request.client else "unknown")
    bucket = _buckets.get(key)
    if bucket is None:
        if len(_buckets) >= 4096:
            expired = [
                k for k, v in _buckets.items() if not v or v[-1] < time.monotonic() - 60
            ]
            for k in expired:
                _buckets.pop(k, None)
            if len(_buckets) >= 4096:
                raise HTTPException(429, "Service busy. Try again shortly.")
        bucket = _buckets[key] = deque()
    stamp = time.monotonic()
    while bucket and bucket[0] < stamp - 60:
        bucket.popleft()
    if len(bucket) >= 120:
        raise HTTPException(429, "Too many requests. Try again shortly.")
    bucket.append(stamp)


async def player(request: Request):
    guard(request)
    return await service.player_for_token(request.cookies.get(COOKIE))


async def operator(
    request: Request, wallet: WalletTypeInfo = Depends(require_admin_key)
):
    guard(request)
    row = await service.settings_record()
    if row:
        if (
            row["owner_id"] != wallet.wallet.user
            or row["wallet_id"] != wallet.wallet.id
        ):
            raise HTTPException(403, "Use the configured game wallet's admin key.")
    elif not settings.is_admin_user(wallet.wallet.user):
        raise HTTPException(
            403, "An LNbits administrator must configure the game first."
        )
    return wallet


async def session_data(p):
    live = await service.game_config()
    current = await competitions.current_competition()
    config = (
        {
            **json.loads(current["config"]),
            "enabled": live["enabled"],
            "leaderboard_enabled": live["leaderboard_enabled"],
        }
        if current
        else live
    )
    runs = await db.fetchall(
        """SELECT * FROM satshole.runs WHERE player_id=:id AND status IN
        ('READY','WAITING_PAYMENT') ORDER BY created_at DESC LIMIT 3""",
        {"id": p["id"]},
    )
    available = []
    for run in runs:
        fresh = await service.reconcile(dict(run))
        if fresh["status"] in ("READY", "WAITING_PAYMENT"):
            available.append(service.public_run(fresh))
    return {
        "player": {"id": p["id"], "display_name": p["display_name"]},
        "free_remaining": max(0, config["free_runs"] - p["free_used"]),
        "config": config,
        "practice_config": {"competitor_aggression": live["competitor_aggression"]},
        "runs": available,
    }


def no_cache(response: Response):
    response.headers["Cache-Control"] = "no-store"


router.dependencies.append(Depends(no_cache))


@router.post("/session")
async def session(request: Request, response: Response):
    guard(request)
    token = request.cookies.get(COOKIE)
    if token:
        try:
            p = await service.player_for_token(token)
        except HTTPException as error:
            if error.status_code != 401:
                raise
            token, p = await service.new_player("Visitor")
    else:
        token, p = await service.new_player("Visitor")
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/satshole",
        max_age=31536000,
    )
    response.headers["Cache-Control"] = "no-store"
    return await session_data(p)


@router.put("/profile")
async def profile(data: Profile, p=Depends(player)):
    await db.execute(
        "UPDATE satshole.players SET display_name=:name WHERE id=:id",
        {"id": p["id"], "name": service.clean_name(data.display_name)},
    )
    return {"display_name": service.clean_name(data.display_name)}


@router.post("/runs")
async def runs(data: RunRequest, p=Depends(player)):
    return service.public_run(await service.create_run(p, data.free))


@router.get("/runs/{run_id}")
async def run_status(run_id: str, p=Depends(player)):
    return service.public_run(
        await service.reconcile(await service.owned_run(run_id, p))
    )


@router.post("/runs/{run_id}/start")
async def start(run_id: str, p=Depends(player)):
    return await service.start_run(run_id, p)


@router.post("/runs/{run_id}/finish")
async def finish(run_id: str, request: Request, p=Depends(player)):
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > 256000:
            raise HTTPException(413, "Input payload too large.")
    try:
        data = FinishRequest.parse_raw(bytes(content))
    except (ValidationError, ValueError):
        raise HTTPException(422, "Malformed input stream.") from None
    return await service.finish_run(run_id, p, data.run_token, data.inputs)


@router.get("/leaderboard")
async def leaderboard(request: Request, competition_id: str | None = None):
    guard(request)
    return await competitions.public_board(competition_id)


@router.get("/competitions")
async def competition_history(request: Request):
    guard(request)
    await competitions.current_competition()
    return await competitions.history()


@router.get("/runs/{run_id}/leaderboard-preview")
async def leaderboard_preview(run_id: str, p=Depends(player)):
    return await competitions.preview(run_id, p)


@router.post("/entries")
async def create_entry(data: EntryRequest, p=Depends(player)):
    return await competitions.create_submission(data.run_id, p, data.lightning_address)


@router.get("/entries/{submission_id}")
async def entry_status(submission_id: str, p=Depends(player)):
    return await competitions.submission_for_player(submission_id, p)


@router.get("/settings")
async def get_settings(wallet=Depends(operator)):
    return {
        "config": await service.game_config(),
        "wallet_id": wallet.wallet.id,
        "configured": bool(await service.settings_record()),
    }


@router.put("/settings")
async def save_settings(data: GameSettings, wallet=Depends(operator)):
    saved = await db.execute(
        """INSERT INTO satshole.game_settings (id,owner_id,wallet_id,config)
        VALUES ('game',:owner,:wallet,:config) ON CONFLICT (id) DO UPDATE SET
        config=excluded.config WHERE game_settings.owner_id=excluded.owner_id
        AND game_settings.wallet_id=excluded.wallet_id""",
        {
            "owner": wallet.wallet.user,
            "wallet": wallet.wallet.id,
            "config": data.json(),
        },
    )
    if saved.rowcount != 1:
        raise HTTPException(403, "Game configuration belongs to another wallet.")
    return {"config": await service.game_config(), "wallet_id": wallet.wallet.id}


@router.get("/metrics")
async def metrics(wallet=Depends(operator)):
    runs = await db.fetchall(
        "SELECT status,paid,COUNT(*) AS total FROM satshole.runs GROUP BY status,paid"
    )
    revenue = await db.fetchone("""SELECT COALESCE(SUM(amount),0) AS amount FROM
        satshole.financial_events WHERE kind='game_revenue'""")
    current = await competitions.current_competition()
    week_metrics = None
    if current:
        summary = await db.fetchone(
            """SELECT COUNT(*) AS runs_created, COALESCE(SUM(CASE WHEN
started_at IS NOT NULL THEN 1 ELSE 0 END),0) AS games_played,
COALESCE(SUM(CASE WHEN started_at IS NOT NULL AND paid=1 THEN 1
ELSE 0 END),0) AS paid_games, COALESCE(SUM(CASE WHEN started_at
IS NOT NULL AND paid=0 THEN 1 ELSE 0 END),0) AS free_games,
COUNT(DISTINCT CASE WHEN started_at IS NOT NULL THEN player_id
ELSE NULL END) AS unique_players, COALESCE(SUM(CASE WHEN
status='VERIFIED' THEN 1 ELSE 0 END),0) AS verified_runs,
COALESCE(SUM(CASE WHEN status='INVALID' THEN 1 ELSE 0 END),0) AS
failed_verifications, COALESCE(AVG(CASE WHEN status='VERIFIED'
THEN authoritative_score ELSE NULL END),0) AS average_score,
COALESCE(MAX(CASE WHEN status='VERIFIED' THEN authoritative_score
ELSE NULL END),0) AS highest_score FROM satshole.runs WHERE
competition_id=:id""",
            {"id": current["id"]},
        )
        week_metrics = {
            "competition_id": current["id"],
            **dict(summary),
            **await competitions.totals(current["id"]),
            "unique_entrants": len(await competitions.ranking(current["id"])),
        }
    payment_counts = await db.fetchone("""SELECT
        COALESCE(SUM(CASE WHEN status!='PAID' THEN 1 ELSE 0 END),0) AS pending,
        COALESCE(SUM(CASE WHEN status='PAID' THEN 1 ELSE 0 END),0) AS completed,
        COALESCE(SUM(CASE WHEN status='RETRY' THEN 1 ELSE 0 END),0) AS retry_needed,
        COALESCE(SUM(CASE WHEN held=1 AND status!='PAID' THEN 1 ELSE 0 END),0) AS held
        FROM satshole.outgoing""")
    accounting = await competitions.totals()
    current_wallet = await get_wallet(wallet.wallet.id)
    wallet_balance = current_wallet.balance_msat // 1000 if current_wallet else 0
    return {
        "current_week": week_metrics,
        "outgoing": dict(payment_counts),
        "runs": [dict(r) for r in runs],
        "game_revenue": revenue["amount"],
        "prize_liability": accounting["prize_liability"],
        "wallet_balance": wallet_balance,
        "balance_less_liabilities": max(
            0,
            wallet_balance
            - accounting["prize_liability"]
            - accounting["refund_liability"],
        ),
        "leaderboard_operator_revenue": accounting["operator_revenue"],
        "refund_liability": accounting["refund_liability"],
    }


@router.get("/operations")
async def settlement_operations(wallet=Depends(operator)):
    return await settlement.operations()


@router.post("/competitions/{competition_id}/prepare")
async def prepare_settlement(
    competition_id: str, data: OperatorAction, wallet=Depends(operator)
):
    await moderation.record_operation(
        "prepare:" + competition_id,
        wallet.wallet.user,
        data.reason,
        str(data.request_id),
    )
    return await settlement.settle(competition_id)


@router.post("/competitions/{competition_id}/settle")
async def pay_settlement(
    competition_id: str, data: OperatorAction, wallet=Depends(operator)
):
    await moderation.record_operation(
        "settle:" + competition_id,
        wallet.wallet.user,
        data.reason,
        str(data.request_id),
    )
    await settlement.settle(competition_id, send=True)
    return await settlement.operations()


@router.post("/payments/{payment_id}/retry")
async def retry_outgoing(
    payment_id: str, data: OperatorAction, wallet=Depends(operator)
):
    row = await db.fetchone(
        "SELECT wallet_id FROM satshole.outgoing WHERE id=:id", {"id": payment_id}
    )
    if not row or row["wallet_id"] != wallet.wallet.id:
        raise HTTPException(404, "Payment not found.")
    await moderation.record_operation(
        "retry:" + payment_id, wallet.wallet.user, data.reason, str(data.request_id)
    )
    await settlement.transfer(payment_id)
    return await settlement.operations()


@router.get("/review")
async def review_runs(
    competition_id: str | None = None, page: int = 0, wallet=Depends(operator)
):
    if page < 0 or page > 10000:
        raise HTTPException(422, "Invalid review page.")
    return await moderation.inspect(competition_id, page)


@router.get("/review/runs/{run_id}")
async def inspect_run(run_id: str, wallet=Depends(operator)):
    return await moderation.inspect_run(run_id)


@router.get("/review/runs/{run_id}/replay")
async def download_run_replay(run_id: str, wallet=Depends(operator)):
    return await moderation.replay_payload(run_id)


@router.post("/review/runs/{run_id}/replay")
async def replay_run(run_id: str, wallet=Depends(operator)):
    from .replay import verify

    payload = await moderation.replay_payload(run_id)
    row = await db.fetchone("SELECT * FROM satshole.runs WHERE id=:id", {"id": run_id})
    try:
        result = await verify(
            {**dict(row), "config": payload["config"]}, payload["inputs"]
        )
    except ValueError:
        raise HTTPException(422, "Stored replay was rejected.") from None
    except Exception:
        raise HTTPException(503, "Replay worker unavailable. Retry shortly.") from None
    return {
        "result": result,
        "recorded_score": row["authoritative_score"],
        "matches": result["score"] == row["authoritative_score"],
    }


@router.post("/review/players/{player_id}")
async def review_player(player_id: str, data: PlayerReview, wallet=Depends(operator)):
    return await moderation.block_player(
        player_id, data.blocked, wallet.wallet.user, data.reason, str(data.request_id)
    )


@router.post("/review/entries/{submission_id}")
async def review_entry(submission_id: str, data: EntryReview, wallet=Depends(operator)):
    return await moderation.review_entry(
        submission_id,
        data.disqualified,
        data.refund,
        wallet.wallet.user,
        data.reason,
        str(data.request_id),
    )


@router.post("/payments/{payment_id}/hold")
async def hold_payment(payment_id: str, data: PaymentHold, wallet=Depends(operator)):
    return await moderation.hold_payment(
        payment_id, data.held, wallet.wallet.user, data.reason, str(data.request_id)
    )


@router.post("/payments/{payment_id}/repair")
async def repair_payment(
    payment_id: str, data: PaymentRepair, wallet=Depends(operator)
):
    return await moderation.repair_payment(
        payment_id,
        data.lightning_address,
        wallet.wallet.user,
        data.reason,
        str(data.request_id),
    )


@router.post("/emergency-pause")
async def emergency_pause(data: OperatorAction, wallet=Depends(operator)):
    return await moderation.emergency_pause(
        wallet.wallet.user, data.reason, str(data.request_id)
    )


@router.get("/review/audit/{event_id}")
async def inspect_audit(event_id: str, wallet=Depends(operator)):
    row = await db.fetchone(
        "SELECT * FROM satshole.operator_events WHERE id=:id", {"id": event_id}
    )
    if not row:
        raise HTTPException(404, "Audit record not found.")
    result = dict(row)
    result["payload"] = json.loads(result["payload"])
    return result


@router.post("/payments/{payment_id}/reconcile")
async def reconcile_outgoing(
    payment_id: str, data: OperatorAction, wallet=Depends(operator)
):
    row = await db.fetchone(
        "SELECT wallet_id FROM satshole.outgoing WHERE id=:id", {"id": payment_id}
    )
    if not row or row["wallet_id"] != wallet.wallet.id:
        raise HTTPException(404, "Payment not found.")
    await moderation.record_operation(
        "reconcile:" + payment_id, wallet.wallet.user, data.reason, str(data.request_id)
    )
    await settlement.transfer(payment_id, send=False)
    return await settlement.operations()
