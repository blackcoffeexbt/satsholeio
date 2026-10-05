"""Weekly competition integration checks; fake Lightning, real LNbits database."""

import json
import types
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

import game_backend as backend
from fastapi import HTTPException

competition = backend.competition
game = backend.service
db = backend.crud.db


class CompetitionTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = backend.BackendTests.asyncSetUp
    asyncTearDown = backend.BackendTests.asyncTearDown

    async def configure(self, **extra):
        self.config.update(leaderboard_enabled=True, **extra)
        await db.execute(
            "UPDATE satshole.game_settings SET config=:config",
            {"config": json.dumps(self.config)},
        )

    async def verified(self, player=None, score=100, paid=True):
        player = player or self.player
        run = await game.create_run(player, True)
        await db.execute(
            """UPDATE satshole.runs SET status='VERIFIED',
            authoritative_score=:score,paid=:paid WHERE id=:id""",
            {"id": run["id"], "score": score, "paid": int(paid)},
        )
        return run

    async def enter(self, run, player=None, settle=True):
        player = player or self.player
        payment = types.SimpleNamespace(
            payment_hash=uuid4().hex,
            bolt11="lnbc-test",
            wallet_id="wallet",
            amount=250000,
            success=False,
            extra={"tag": "satshole_entry"},
        )

        async def invoice(**kwargs):
            payment.amount = kwargs["amount"] * 1000
            payment.extra.update(kwargs["extra"])
            return payment

        async def status(*args, **kwargs):
            return payment

        with (
            patch.object(competition, "create_invoice", invoice),
            patch.object(competition, "get_standalone_payment", status),
        ):
            entry = await competition.create_submission(
                run["id"], player, "player@example.com"
            )
            self.assertEqual(entry["status"], "PENDING")
            if settle:
                payment.success = True
                await competition.record_entry_payment(payment)
        return entry, payment

    async def test_verified_only_paid_only_owned_run(self):
        await self.configure()
        run = await game.create_run(self.player, True)
        with self.assertRaises(HTTPException):
            await competition.create_submission(run["id"], self.player, "a@example.com")
        run = await self.verified(paid=False)
        with self.assertRaises(HTTPException):
            await competition.create_submission(run["id"], self.player, "a@example.com")
        with self.assertRaises(HTTPException):
            await competition.create_submission(run["id"], self.other, "a@example.com")

    async def test_duplicate_receipt_and_exact_80_20(self):
        await self.configure()
        run = await self.verified(score=420)
        entry, payment = await self.enter(run)
        await competition.record_entry_payment(payment)
        comp = await competition.current_competition()
        totals = await competition.totals(comp["id"])
        self.assertEqual(totals["prize_liability"], 200)
        self.assertEqual(totals["operator_revenue"], 50)
        self.assertEqual(totals["paid_receipts"], 1)
        board = await competition.public_board()
        self.assertEqual(board["rankings"][0]["score"], 420)
        self.assertEqual(board["pot"], 200)
        self.assertNotIn("player_id", board["rankings"][0])
        self.assertNotIn("payment_hash", str(board))
        self.assertNotIn("player@example.com", str(board))
        self.assertEqual(
            (await competition.submission_for_player(entry["id"], self.player))[
                "status"
            ],
            "ENTRY_CREATED",
        )

    async def test_highest_score_per_player_and_first_entry_ties(self):
        await self.configure()
        run = await self.verified(score=100)
        await self.enter(run)
        run = await self.verified(self.other, score=150)
        await self.enter(run, self.other)
        run = await self.verified(score=150)
        await self.enter(run)
        board = await competition.public_board()
        self.assertEqual(board["unique_entrants"], 2)
        self.assertEqual(board["paid_submissions"], 3)
        self.assertEqual(
            [r["display_name"] for r in board["rankings"]], ["Other", "Player"]
        )
        self.assertEqual(board["pot"], 600)

    async def test_cutoff_late_payment_is_fully_refundable(self):
        await self.configure()
        run = await self.verified()
        entry, payment = await self.enter(run, settle=False)
        old = await competition.current_competition()
        self.stamp = old["ends_at"]
        payment.success = True
        await competition.record_entry_payment(payment)
        await competition.record_entry_payment(payment)
        totals = await competition.totals(old["id"])
        self.assertEqual(totals["prize_liability"], 0)
        self.assertEqual(totals["operator_revenue"], 0)
        self.assertEqual(totals["refund_liability"], 250)
        self.assertEqual(
            (await competition.submission_for_player(entry["id"], self.player))[
                "status"
            ],
            "REFUND_PENDING",
        )
        new = await competition.current_competition()
        self.assertNotEqual(new["id"], old["id"])
        self.assertEqual(
            (await competition.competition_by_id(old["id"]))["status"], "CLOSED"
        )
        self.assertFalse(
            (await competition.preview(run["id"], self.player))["eligible"]
        )

    async def test_financial_configuration_is_snapshotted(self):
        await self.configure()
        run = await self.verified()
        old = await competition.current_competition()
        self.config.update(leaderboard_price=999, prize_percentage=50)
        await db.execute(
            "UPDATE satshole.game_settings SET config=:config",
            {"config": json.dumps(self.config)},
        )
        entry, payment = await self.enter(run)
        self.assertEqual(entry["amount"], 250)
        self.assertEqual((await competition.totals(old["id"]))["prize_liability"], 200)
        self.stamp = old["ends_at"]
        new = await competition.current_competition()
        self.assertEqual(json.loads(new["config"])["leaderboard_price"], 999)

    async def test_duplicate_after_close_retains_original_eligibility(self):
        await self.configure()
        run = await self.verified()
        entry, payment = await self.enter(run)
        old = await competition.current_competition()
        self.stamp = old["ends_at"] + 10
        await competition.current_competition()
        await competition.record_entry_payment(payment)
        self.assertEqual(
            (await competition.submission_for_player(entry["id"], self.player))[
                "status"
            ],
            "ENTRY_CREATED",
        )
        self.assertEqual((await competition.totals(old["id"]))["refund_liability"], 0)
        self.assertEqual(
            len((await competition.public_board(old["id"]))["rankings"]), 1
        )

    async def test_invoice_renewal_and_double_payment_refund(self):
        await self.configure()
        run = await self.verified()
        entry, first = await self.enter(run, settle=False)
        self.stamp += 601

        # Existing unpaid invoice expires; same verified run can request another.
        async def old_status(*args, **kwargs):
            return first

        with patch.object(competition, "get_standalone_payment", old_status):
            self.assertEqual(
                (await competition.submission_for_player(entry["id"], self.player))[
                    "status"
                ],
                "EXPIRED",
            )
        second = types.SimpleNamespace(
            payment_hash=uuid4().hex,
            bolt11="lnbc-new",
            wallet_id="wallet",
            amount=250000,
            success=False,
            extra={"tag": "satshole_entry"},
        )

        async def invoice(**kwargs):
            second.extra.update(kwargs["extra"])
            return second

        async def status(hash, *args, **kwargs):
            return first if hash == first.payment_hash else second

        with (
            patch.object(competition, "create_invoice", invoice),
            patch.object(competition, "get_standalone_payment", status),
        ):
            renewed = await competition.create_submission(
                run["id"], self.player, "player@example.com"
            )
            self.assertEqual(renewed["id"], entry["id"])
            self.assertEqual(renewed["bolt11"], "lnbc-new")
            first.success = second.success = True
            await competition.record_entry_payment(first)
            await competition.record_entry_payment(second)
            await competition.record_entry_payment(second)
            totals = await competition.totals()
            self.assertEqual(totals["prize_liability"], 200)
            self.assertEqual(totals["operator_revenue"], 50)
            self.assertEqual(totals["refund_liability"], 250)
            self.assertEqual((await competition.public_board())["paid_submissions"], 1)

    async def test_operational_invoice_failure_can_retry(self):
        await self.configure()
        run = await self.verified()

        async def missing(*args, **kwargs):
            return []

        async def broken(**kwargs):
            raise RuntimeError("offline")

        with (
            patch.object(competition, "create_invoice", broken),
            patch.object(competition, "get_payments", missing),
        ):
            with self.assertRaises(HTTPException):
                await competition.create_submission(
                    run["id"], self.player, "player@example.com"
                )
        with patch.object(competition, "get_payments", missing):
            entry, payment = await self.enter(run)
        self.assertEqual(
            (await competition.submission_for_player(entry["id"], self.player))[
                "status"
            ],
            "ENTRY_CREATED",
        )

    async def test_paid_attempt_recovers_before_ledger_commit(self):
        await self.configure()
        run = await self.verified()
        entry, payment = await self.enter(run, settle=False)
        payment.success = True
        await db.execute(
            "UPDATE satshole.entry_invoices SET status='PAID' WHERE submission_id=:id",
            {"id": entry["id"]},
        )

        async def status(*args, **kwargs):
            return payment

        with patch.object(competition, "get_standalone_payment", status):
            recovered = await competition.submission_for_player(
                entry["id"], self.player
            )
        self.assertEqual(recovered["status"], "ENTRY_CREATED")
        self.assertEqual((await competition.totals())["prize_liability"], 200)

    def test_dst_safe_close_and_rounding(self):
        config = {**competition.DEFAULTS}
        march = int(datetime(2026, 3, 28, 12, tzinfo=timezone.utc).timestamp())
        start, end = competition.week_bounds(march, config)
        self.assertEqual(datetime.fromtimestamp(end, timezone.utc).hour, 20)
        self.assertEqual(end - start, 167 * 3600)
        october = int(datetime(2026, 10, 24, 12, tzinfo=timezone.utc).timestamp())
        start, end = competition.week_bounds(october, config)
        self.assertEqual(datetime.fromtimestamp(end, timezone.utc).hour, 21)
        self.assertEqual(end - start, 169 * 3600)
        for pot in range(1000):
            amounts = competition.prizes(pot, config)
            self.assertEqual(sum(amounts), pot)
            self.assertTrue(all(a >= 0 for a in amounts))

    def test_address_and_settings_validation(self):
        self.assertEqual(
            competition.payout_address("Player@Example.com"), "player@example.com"
        )
        for value in [
            "a@localhost",
            "<b>@example.com",
            "a@127.0.0.1",
            "a@evil.local",
            "a@https://example.com",
        ]:
            with self.assertRaises(HTTPException):
                competition.payout_address(value)
        with self.assertRaises(ValueError):
            backend.api.GameSettings(first_percentage=99)
        with self.assertRaises(ValueError):
            backend.api.GameSettings(timezone="Fake/Zone")


if __name__ == "__main__":
    unittest.main()
