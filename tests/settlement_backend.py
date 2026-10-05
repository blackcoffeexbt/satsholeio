"""Settlement recovery checks using fake outgoing Lightning payments."""

import asyncio
import json
import types
import unittest
from unittest.mock import patch

import competition_backend as fixture

backend = fixture.backend
competition = fixture.competition
db = fixture.db

settlement = backend.settlement


class SettlementTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.CompetitionTests.asyncSetUp
    asyncTearDown = fixture.CompetitionTests.asyncTearDown
    configure = fixture.CompetitionTests.configure
    verified = fixture.CompetitionTests.verified
    enter = fixture.CompetitionTests.enter

    async def close(self):
        current = await competition.current_competition()
        self.stamp = current["ends_at"] + 3600
        await competition.current_competition()
        return current["id"]

    async def test_review_delay(self):
        await self.configure()
        current = await competition.current_competition()
        self.stamp = current["ends_at"]
        with self.assertRaises(Exception):
            await settlement.plan(current["id"])

    async def test_single_winner_carry_and_frozen_idempotent_plan(self):
        await self.configure()
        await self.enter(await self.verified(score=400))
        old = await self.close()
        first, second = await asyncio.gather(
            settlement.settle(old), settlement.settle(old)
        )
        self.assertEqual(first, second)
        winners = json.loads(first["plan"])
        self.assertEqual([w["amount"] for w in winners], [140])
        self.assertEqual(first["carry_amount"], 60)
        self.assertEqual((await competition.totals(old))["prize_liability"], 140)
        self.assertEqual((await competition.public_board())["pot"], 60)
        # Frozen recipients are unaffected by subsequent player changes.
        await db.execute("UPDATE satshole.players SET blocked=1")
        self.assertEqual((await settlement.plan(old))["plan"], first["plan"])

    async def test_no_entrants_and_rounding_conserve_pot(self):
        await self.configure()
        await self.enter(await self.verified())
        await db.execute("UPDATE satshole.players SET blocked=1")
        old = await self.close()
        frozen = await settlement.settle(old)
        self.assertEqual(frozen["carry_amount"], 200)
        self.assertEqual(json.loads(frozen["plan"]), [])
        self.assertEqual(
            (await competition.competition_by_id(old))["status"], "SETTLED"
        )

    async def test_pinned_invoice_pending_restart_and_paid_once(self):
        await self.configure()
        await self.enter(await self.verified())
        old = await self.close()
        frozen = await settlement.settle(old)
        key = json.loads(frozen["plan"])[0]["id"]
        state = {"native": None, "invoice_calls": 0, "send_calls": 0}

        async def invoice(*args):
            state["invoice_calls"] += 1
            return "saved-invoice"

        async def native(*args, **kwargs):
            return state["native"]

        async def send(**kwargs):
            state["send_calls"] += 1
            state["native"] = types.SimpleNamespace(
                wallet_id="wallet", amount=-140000, success=False, pending=True
            )
            raise RuntimeError("network timeout after send")

        with (
            patch.object(settlement, "get_pr_from_lnurl", invoice),
            patch.object(
                settlement,
                "decode",
                lambda _: types.SimpleNamespace(
                    amount_msat=140000, payment_hash="winner-hash"
                ),
            ),
            patch.object(settlement, "get_standalone_payment", native),
            patch.object(settlement, "pay_invoice", send),
        ):
            await settlement.transfer(key)
            await settlement.transfer(key)
            self.assertEqual(state["send_calls"], 1)
            state["native"].success = True
            state["native"].pending = False
            await settlement.settle(old, send=True)
            await settlement.settle(old, send=True)
        self.assertEqual(state["invoice_calls"], 1)
        self.assertEqual((await competition.totals())["prize_liability"], 60)
        self.assertEqual(
            (await competition.competition_by_id(old))["status"], "SETTLED"
        )

    async def test_wrong_invoice_amount_never_sends(self):
        await settlement.obligation(
            "refund:test", "REFUND", "test", "wallet", "a@example.com", 250
        )

        async def invoice(*args):
            return "wrong"

        async def send(**kwargs):
            self.fail("must not send mismatched invoice")

        with (
            patch.object(settlement, "get_pr_from_lnurl", invoice),
            patch.object(
                settlement,
                "decode",
                lambda _: types.SimpleNamespace(amount_msat=1, payment_hash="bad"),
            ),
            patch.object(settlement, "pay_invoice", send),
        ):
            result = await settlement.transfer("refund:test")
        self.assertEqual(result["status"], "RETRY")
        self.assertIsNone(result["payment_hash"])

    async def test_refund_success_reduces_liability_once_and_records_fee(self):
        await self.configure()
        _, payment = await self.enter(await self.verified(), settle=False)
        await self.close()
        payment.success = True
        await competition.record_entry_payment(payment)
        await settlement.prepare_refunds()
        key = "refund:" + payment.payment_hash
        native = types.SimpleNamespace(
            wallet_id="wallet", amount=-250000, success=True, pending=False, fee=-1500
        )

        async def invoice(*args):
            return "refund-invoice"

        async def status(*args, **kwargs):
            return native

        with (
            patch.object(settlement, "get_pr_from_lnurl", invoice),
            patch.object(
                settlement,
                "decode",
                lambda _: types.SimpleNamespace(
                    amount_msat=250000, payment_hash="refund-hash"
                ),
            ),
            patch.object(settlement, "get_standalone_payment", status),
        ):
            await settlement.transfer(key)
            await settlement.transfer(key)
        self.assertEqual((await competition.totals())["refund_liability"], 0)
        rows = await db.fetchall("SELECT * FROM satshole.outgoing_receipts")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["fee_msat"], 1500)

    async def test_foreign_native_payment_never_confirms_or_sends(self):
        await settlement.obligation(
            "foreign", "REFUND", "test", "wallet", "a@example.com", 250
        )

        async def invoice(*args):
            return "foreign-invoice"

        async def status(*args, **kwargs):
            return types.SimpleNamespace(
                wallet_id="other", amount=-250000, success=True
            )

        async def send(**kwargs):
            self.fail("Foreign native payment must not trigger a send")

        with (
            patch.object(settlement, "get_pr_from_lnurl", invoice),
            patch.object(
                settlement,
                "decode",
                lambda _: types.SimpleNamespace(
                    amount_msat=250000, payment_hash="foreign-hash"
                ),
            ),
            patch.object(settlement, "get_standalone_payment", status),
            patch.object(settlement, "pay_invoice", send),
        ):
            result = await settlement.transfer("foreign")
        self.assertEqual(result["status"], "RETRY")
        self.assertEqual(
            len(await db.fetchall("SELECT * FROM satshole.outgoing_receipts")), 0
        )

    async def test_hold_policy_preserves_unallocated_liability(self):
        await self.configure(undistributed_policy="hold")
        await self.enter(await self.verified())
        old = await self.close()
        frozen = await settlement.settle(old)
        self.assertEqual(frozen["carry_to"], old)
        self.assertEqual((await competition.totals(old))["prize_liability"], 200)
        self.assertEqual((await competition.public_board())["pot"], 0)

    async def test_late_refund_preparation_is_unique(self):
        await self.configure()
        entry, payment = await self.enter(await self.verified(), settle=False)
        old = await self.close()
        payment.success = True
        await competition.record_entry_payment(payment)
        await settlement.prepare_refunds()
        await settlement.prepare_refunds()
        rows = await db.fetchall("SELECT * FROM satshole.outgoing WHERE kind='REFUND'")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["amount"], 250)
        self.assertEqual(rows[0]["address"], "player@example.com")
        self.assertEqual((await competition.totals(old))["refund_liability"], 250)


if __name__ == "__main__":
    unittest.main()
