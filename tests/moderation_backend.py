"""Audited moderation and payment repair checks with fake Lightning I/O."""

import json
import types
import unittest
from unittest.mock import patch
from uuid import uuid4

import settlement_backend as fixture
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

backend = fixture.backend
db = fixture.db
moderation = backend.moderation
settlement = backend.settlement
competition = backend.competition


class OperatorTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.SettlementTests.asyncSetUp
    asyncTearDown = fixture.SettlementTests.asyncTearDown
    configure = fixture.SettlementTests.configure
    verified = fixture.SettlementTests.verified
    enter = fixture.SettlementTests.enter
    close = fixture.SettlementTests.close

    async def block(self, value=True, request_id=None):
        return await moderation.block_player(
            self.player["id"],
            value,
            "owner",
            "Operator review",
            request_id or str(uuid4()),
        )

    async def review(self, entry, disqualified=True, refund=False, request_id=None):
        return await moderation.review_entry(
            entry["id"],
            disqualified,
            refund,
            "owner",
            "Score review",
            request_id or str(uuid4()),
        )

    async def test_block_unblock_and_identity_gate(self):
        await self.configure()
        await self.enter(await self.verified(score=300))
        await self.enter(await self.verified(self.other, score=200), self.other)
        await self.block()
        with self.assertRaises(HTTPException):
            await backend.service.player_for_token(self.token)
        board = await competition.public_board()
        self.assertEqual([r["display_name"] for r in board["rankings"]], ["Other"])
        await self.block(False)
        self.assertEqual(
            (await backend.service.player_for_token(self.token))["blocked"], 0
        )
        self.assertEqual(
            (await competition.public_board())["rankings"][0]["display_name"], "Player"
        )

    async def test_disqualification_falls_back_to_previous_best_and_can_restore(self):
        await self.configure()
        await self.enter(await self.verified(score=100))
        second, payment = await self.enter(await self.verified(score=500))
        await self.review(second)
        await competition.record_entry_payment(payment)
        self.assertEqual(
            (await competition.public_board())["rankings"][0]["score"], 100
        )
        self.assertEqual((await competition.totals())["prize_liability"], 400)
        await self.review(second, False)
        self.assertEqual(
            (await competition.public_board())["rankings"][0]["score"], 500
        )

    async def test_refund_reallocates_full_fee_once_and_cannot_restore(self):
        await self.configure()
        entry, _ = await self.enter(await self.verified())
        request_id = str(uuid4())
        await self.review(entry, refund=True, request_id=request_id)
        await self.review(entry, refund=True, request_id=request_id)
        await self.review(entry, refund=True)
        totals = await competition.totals()
        self.assertEqual(
            [
                totals[k]
                for k in ["prize_liability", "operator_revenue", "refund_liability"]
            ],
            [0, 0, 250],
        )
        self.assertEqual((await competition.public_board())["rankings"], [])
        self.assertEqual(len(await db.fetchall("SELECT * FROM satshole.outgoing")), 1)
        with self.assertRaises(HTTPException):
            await self.review(entry, False)
        self.assertEqual(
            len(await db.fetchall("SELECT * FROM satshole.competition_events")), 1
        )
        status = await competition.submission_for_player(entry["id"], self.player)
        self.assertTrue(status["disqualified"])
        self.assertEqual(
            (status["refund_amount"], status["refund_status"]), (250, "PENDING")
        )
        with self.assertRaises(HTTPException):
            await competition.submission_for_player(entry["id"], self.other)

    async def test_frozen_ranking_and_prizes_survive_blocking(self):
        await self.configure()
        entry, _ = await self.enter(await self.verified(score=999))
        old = await self.close()
        frozen = await settlement.settle(old)
        await self.block()
        historical = await competition.public_board(old)
        self.assertEqual(historical["rankings"][0]["score"], 999)
        self.assertFalse(historical["entries_enabled"])
        with self.assertRaises(HTTPException):
            await self.review(entry, refund=True)
        self.assertEqual((await settlement.plan(old))["plan"], frozen["plan"])
        self.assertEqual((await competition.totals(old))["prize_liability"], 140)

    async def test_audit_idempotency_does_not_revert_later_action(self):
        request_id = str(uuid4())
        await self.block(request_id=request_id)
        await self.block(False)
        await self.block(request_id=request_id)
        self.assertEqual(
            (await backend.service.player_for_token(self.token))["blocked"], 0
        )
        with self.assertRaises(HTTPException):
            await self.block(False, request_id=request_id)
        events = await db.fetchall(
            "SELECT * FROM satshole.operator_events ORDER BY seq"
        )
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["actor_id"], "owner")
        self.assertEqual(events[0]["reason"], "Operator review")

    async def test_audit_recovers_interrupted_refund_before_settlement_freezes(self):
        await self.configure()
        entry, _ = await self.enter(await self.verified())

        async def unavailable(event):
            raise RuntimeError("crash after journal insert")

        with patch.object(moderation, "apply_event", unavailable):
            with self.assertRaises(RuntimeError):
                await self.review(entry, refund=True)
        old = await self.close()
        frozen = await settlement.settle(old)
        self.assertEqual(json.loads(frozen["plan"]), [])
        self.assertEqual((await competition.totals())["refund_liability"], 250)
        self.assertEqual(
            len(await db.fetchall("SELECT * FROM satshole.operator_applied")), 1
        )

    async def outgoing(self, payment_hash=None, attempted=None, state="READY"):
        await settlement.obligation(
            "test-payment", "PRIZE", "test", "wallet", "old@example.com", 100
        )
        await db.execute(
            """UPDATE satshole.outgoing SET payment_hash=:hash,bolt11=:bolt,
            send_started_at=:attempt,status=:state WHERE id=:id""",
            {
                "id": "test-payment",
                "hash": payment_hash,
                "bolt": "old-invoice" if payment_hash else None,
                "attempt": attempted,
                "state": state,
            },
        )

    async def repair(self, request_id=None):
        return await moderation.repair_payment(
            "test-payment",
            "new@example.com",
            "owner",
            "Recipient verified",
            request_id or str(uuid4()),
        )

    async def test_never_sent_repair_stays_held_and_keeps_allocation(self):
        await self.outgoing()
        request_id = str(uuid4())
        await self.repair(request_id)
        await self.repair(request_id)
        row = await settlement.transfer("test-payment")
        self.assertEqual(
            (row["address"], row["amount"], row["held"]), ("new@example.com", 100, 1)
        )
        self.assertIsNone(row["payment_hash"])
        events = await db.fetchall("SELECT * FROM satshole.operator_events")
        self.assertEqual(len(events), 1)
        self.assertEqual(
            json.loads(events[0]["payload"])["before"]["address"], "old@example.com"
        )

    async def test_unknown_attempt_and_pending_native_cannot_be_repaired(self):
        await self.outgoing(payment_hash="old-hash", attempted=999, state="RETRY")

        async def absent(*args, **kwargs):
            return None

        with patch.object(settlement, "get_standalone_payment", absent):
            with self.assertRaises(HTTPException):
                await self.repair()

        async def pending(*args, **kwargs):
            return types.SimpleNamespace(
                wallet_id="wallet",
                amount=-100000,
                success=False,
                pending=True,
                failed=False,
            )

        with patch.object(settlement, "get_standalone_payment", pending):
            with self.assertRaises(HTTPException):
                await self.repair()
        self.assertEqual(
            len(await db.fetchall("SELECT * FROM satshole.operator_events")), 0
        )

    async def test_failed_repair_requires_expiry_and_fresh_failure(self):
        await self.outgoing(payment_hash="old-hash", attempted=999, state="RETRY")

        async def failed(*args, **kwargs):
            return types.SimpleNamespace(
                wallet_id="wallet",
                amount=-100000,
                success=False,
                pending=False,
                failed=True,
            )

        status = {"failed": False}

        async def fresh(*args):
            return types.SimpleNamespace(**status)

        expiry = {"at": 2000}
        with (
            patch.object(settlement, "get_standalone_payment", failed),
            patch.object(
                settlement,
                "decode",
                lambda _: types.SimpleNamespace(expiry_date=expiry["at"]),
            ),
            patch.object(moderation, "check_payment_status", fresh),
        ):
            with self.assertRaises(HTTPException):
                await self.repair()
            expiry["at"] = 500
            with self.assertRaises(HTTPException):
                await self.repair()
            status["failed"] = True
            await self.repair()
        row = await db.fetchone("SELECT * FROM satshole.outgoing")
        self.assertIsNone(row["payment_hash"])
        self.assertEqual(row["held"], 1)
        event = await db.fetchone("SELECT * FROM satshole.operator_events")
        self.assertEqual(
            json.loads(event["payload"])["before"]["payment_hash"], "old-hash"
        )

    async def test_completed_native_receipt_is_reconciled_and_repair_refused(self):
        await self.outgoing(payment_hash="old-hash", attempted=999, state="RETRY")

        async def paid(*args, **kwargs):
            return types.SimpleNamespace(
                wallet_id="wallet", amount=-100000, success=True, fee=0
            )

        with patch.object(settlement, "get_standalone_payment", paid):
            with self.assertRaises(HTTPException):
                await self.repair()
        self.assertEqual(
            (await db.fetchone("SELECT * FROM satshole.outgoing"))["status"], "PAID"
        )
        self.assertEqual(
            len(await db.fetchall("SELECT * FROM satshole.outgoing_receipts")), 1
        )

    async def test_emergency_pause_and_automatic_transfer_guard(self):
        await self.configure(automatic_payouts=True)
        await self.outgoing()
        await moderation.emergency_pause("owner", "Emergency review", str(uuid4()))
        config = await backend.service.game_config()
        self.assertFalse(
            any(
                config[k]
                for k in ("enabled", "leaderboard_enabled", "automatic_payouts")
            )
        )

        async def invoice(*args):
            self.fail("Paused automation must not request an invoice")

        with patch.object(settlement, "get_pr_from_lnurl", invoice):
            row = await settlement.transfer("test-payment", automatic=True)
        self.assertEqual(row["status"], "READY")

    async def test_held_payment_can_reconcile_success_without_sending(self):
        await self.outgoing(payment_hash="old-hash", attempted=999, state="PENDING")
        await moderation.hold_payment(
            "test-payment", True, "owner", "Review payment", str(uuid4())
        )

        async def paid(*args, **kwargs):
            return types.SimpleNamespace(
                wallet_id="wallet", amount=-100000, success=True, fee=0
            )

        async def send(**kwargs):
            self.fail("Held payment cannot send")

        with (
            patch.object(settlement, "get_standalone_payment", paid),
            patch.object(settlement, "pay_invoice", send),
        ):
            row = await settlement.transfer("test-payment")
        self.assertEqual(row["status"], "PAID")
        self.assertEqual(row["held"], 1)

    async def test_operator_replay_uses_committed_payload_and_never_rewrites_score(
        self,
    ):
        app = FastAPI()
        app.include_router(backend.api.router, prefix="/satshole")
        wallet = types.SimpleNamespace(
            wallet=types.SimpleNamespace(id="wallet", user="owner")
        )
        app.dependency_overrides[backend.api.require_admin_key] = lambda: wallet
        run = await self.verified(score=999)
        await db.execute(
            "UPDATE satshole.runs SET input_log='[]' WHERE id=:id", {"id": run["id"]}
        )
        captured = {}

        async def verify(row, inputs):
            captured.update(row)
            self.assertEqual(inputs, [])
            return {"score": 998}

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://test"
        ) as client:
            path = "/satshole/api/v1/game/review/runs/" + run["id"] + "/replay"
            with patch("satshole_test.replay.verify", verify):
                response = await client.post(path, json={"seed": 1, "score": 100000})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()["matches"])
            self.assertEqual(captured["seed"], run["seed"])
            self.assertEqual(
                (
                    await db.fetchone(
                        "SELECT authoritative_score FROM satshole.runs WHERE id=:id",
                        {"id": run["id"]},
                    )
                )["authoritative_score"],
                999,
            )
            exported = (await client.get(path)).json()
            self.assertEqual(exported["version"], run["game_version"])
            self.assertEqual(exported["inputs"], [])

    async def test_current_week_metrics_use_persisted_runs_and_refund_ledger(self):
        await self.configure()
        first = await self.verified(score=100)
        await self.verified(self.other, score=200, paid=False)
        await db.execute(
            "UPDATE satshole.runs SET started_at=100 WHERE status='VERIFIED'"
        )
        await backend.service.create_run(self.player, True)  # Ready is not played.
        entry, _ = await self.enter(first)
        await self.review(entry, refund=True)
        wallet = types.SimpleNamespace(wallet=types.SimpleNamespace(id="wallet"))

        async def native_wallet(*args):
            return types.SimpleNamespace(balance_msat=1000000)

        with patch.object(backend.api, "get_wallet", native_wallet):
            metrics = await backend.api.metrics(wallet)
        week = metrics["current_week"]
        self.assertEqual(
            (
                week["games_played"],
                week["paid_games"],
                week["free_games"],
                week["unique_players"],
            ),
            (2, 1, 1, 2),
        )
        self.assertEqual(
            (week["verified_runs"], week["average_score"], week["highest_score"]),
            (2, 150, 200),
        )
        self.assertEqual(
            (
                week["prize_liability"],
                week["refund_liability"],
                week["unique_entrants"],
            ),
            (0, 250, 0),
        )
        self.assertEqual(metrics["balance_less_liabilities"], 750)
        self.assertEqual(metrics["outgoing"]["pending"], 1)

    async def test_reconcile_only_never_resolves_or_sends_an_invoice(self):
        await self.outgoing()

        async def invoice(*args):
            self.fail("Reconciliation must not request an invoice")

        with patch.object(settlement, "get_pr_from_lnurl", invoice):
            row = await settlement.transfer("test-payment", send=False)
        self.assertEqual(row["status"], "READY")
        self.assertIsNone(row["payment_hash"])

    async def test_review_flags_are_observations_and_never_change_rankings(self):
        await self.configure(free_runs=100)
        first = await self.verified(score=999)
        second = await self.verified(self.other, score=400)
        await db.execute(
            """UPDATE satshole.runs SET input_hash='same-input',
            input_log='[]',seed=42,result=:result,started_at=100,
            finished_at=101 WHERE id IN (:first,:second)""",
            {
                "first": first["id"],
                "second": second["id"],
                "result": json.dumps({"score": 1}),
            },
        )
        for _ in range(3):
            run = await backend.service.create_run(self.player, True)
            await db.execute(
                "UPDATE satshole.runs SET status='INVALID' WHERE id=:id",
                {"id": run["id"]},
            )
        review = await moderation.inspect()
        flags = next(r["flags"] for r in review["runs"] if r["id"] == first["id"])
        self.assertIn("Stored score differs from replay result", flags)
        self.assertIn("Same seed and input commitment used by another player", flags)
        self.assertIn("Finish recorded before run duration elapsed", flags)
        self.assertIn("Player has three or more rejected replays in 24 hours", flags)
        self.assertNotIn("seed", review["runs"][0])
        self.assertEqual(
            (await backend.service.player_for_token(self.token))["blocked"], 0
        )
        self.assertEqual(
            (
                await db.fetchone(
                    "SELECT status FROM satshole.runs WHERE id=:id", {"id": first["id"]}
                )
            )["status"],
            "VERIFIED",
        )

    async def test_receipt_only_completion_closes_the_frozen_competition(self):
        await self.configure()
        await self.enter(await self.verified())
        old = await self.close()
        frozen = await settlement.settle(old)
        key = json.loads(frozen["plan"])[0]["id"]
        await db.execute(
            "UPDATE satshole.outgoing SET payment_hash='completed-hash' WHERE id=:id",
            {"id": key},
        )

        async def paid(*args, **kwargs):
            return types.SimpleNamespace(
                wallet_id="wallet", amount=-140000, success=True, fee=0
            )

        with patch.object(settlement, "get_standalone_payment", paid):
            await settlement.transfer(key, send=False)
        self.assertEqual(
            (await competition.competition_by_id(old))["status"], "SETTLED"
        )
        self.assertEqual(
            (await competition.public_board(old))["rankings"][0]["estimated_prize"], 140
        )

    async def test_operator_http_permissions_validation_and_replay_privacy(self):
        app = FastAPI()
        app.include_router(backend.api.router, prefix="/satshole")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://test"
        ) as client:
            for path in ["review", "review/runs/x", "review/audit/x"]:
                self.assertNotEqual(
                    (await client.get("/satshole/api/v1/game/" + path)).status_code, 200
                )
            wrong = types.SimpleNamespace(
                wallet=types.SimpleNamespace(id="foreign", user="owner")
            )
            app.dependency_overrides[backend.api.require_admin_key] = lambda: wrong
            self.assertEqual(
                (await client.get("/satshole/api/v1/game/review")).status_code, 403
            )
            wallet = types.SimpleNamespace(
                wallet=types.SimpleNamespace(id="wallet", user="owner")
            )
            app.dependency_overrides[backend.api.require_admin_key] = lambda: wallet
            run = await self.verified()
            review = await client.get("/satshole/api/v1/game/review")
            self.assertEqual(review.status_code, 200)
            self.assertNotIn("seed", review.text)
            self.assertNotIn("token_hash", review.text)
            action = {"blocked": True, "request_id": str(uuid4()), "reason": "   "}
            path = "/satshole/api/v1/game/review/players/" + self.player["id"]
            self.assertEqual((await client.post(path, json=action)).status_code, 422)
            action["reason"] = "HTTP review"
            self.assertEqual(
                (
                    await client.post(
                        path, json=action, headers={"Origin": "https://evil.example"}
                    )
                ).status_code,
                403,
            )
            self.assertEqual((await client.post(path, json=action)).status_code, 200)
            response = await client.get(
                "/satshole/api/v1/game/review/runs/" + run["id"]
            )
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("seed", response.text)
            self.assertEqual(
                len(await db.fetchall("SELECT * FROM satshole.operator_events")), 1
            )


if __name__ == "__main__":
    unittest.main()
