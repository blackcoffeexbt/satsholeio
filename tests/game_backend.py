"""Integration checks against LNbits' real SQLite abstraction, with fake Lightning IO.
Run using the LNbits environment: python tests/game_backend.py
"""

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sandbox = tempfile.TemporaryDirectory(prefix="satshole-tests-")
os.environ["LNBITS_DATA_FOLDER"] = sandbox.name
from lnbits.db import Database
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("satshole_test")
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package
crud = types.ModuleType("satshole_test.crud")
crud.db = Database("ext_satshole")
sys.modules[crud.__name__] = crud


def load(name):
    spec = importlib.util.spec_from_file_location(
        "satshole_test." + name, ROOT / (name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    setattr(package, name, module)
    spec.loader.exec_module(module)
    return module


migrations = load("migrations")
service = load("game_service")
competition = load("competitions")
api = load("game_api")


class BackendTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if not getattr(self.__class__, "migrated", False):
            await migrations.m003_game_runs(crud.db)
            await migrations.m004_competitions(crud.db)
            await migrations.m005_entry_invoice_attempts(crud.db)
            self.__class__.migrated = True
        for table in [
            "entry_overpayments",
            "entry_invoices",
            "competition_events",
            "submissions",
            "competitions",
            "financial_events",
            "runs",
            "players",
            "game_settings",
        ]:
            await crud.db.execute("DELETE FROM satshole." + table)
        self.stamp = 1000
        self.clock = patch.object(service, "now", lambda: self.stamp)
        self.clock.start()
        self.config = {**service.DEFAULTS, "duration": 10}
        await crud.db.execute(
            "INSERT INTO satshole.game_settings VALUES ('game','owner','wallet',:config)",
            {"config": json.dumps(self.config)},
        )
        self.token, self.player = await service.new_player("Player")
        self.other_token, self.other = await service.new_player("Other")

    async def asyncTearDown(self):
        self.clock.stop()

    async def free(self):
        return await service.create_run(self.player, True)

    async def test_free_allowance_and_one_use_start(self):
        run = await self.free()
        self.assertNotIn("seed", service.public_run(run))
        results = await asyncio.gather(
            service.start_run(run["id"], self.player),
            service.start_run(run["id"], self.player),
            return_exceptions=True,
        )
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        await self.free()
        await self.free()
        with self.assertRaises(HTTPException):
            await self.free()
        with self.assertRaises(HTTPException):
            await service.start_run(run["id"], self.other)

    async def test_unpaid_expiry_late_payment_and_duplicate_accounting(self):
        payment = types.SimpleNamespace(
            payment_hash="hash1",
            bolt11="lnbc-test",
            wallet_id="wallet",
            amount=25000,
            success=False,
            extra={"tag": "satshole_game"},
        )

        async def invoice(**kwargs):
            return payment

        async def status(*args, **kwargs):
            return payment

        with (
            patch.object(service, "create_invoice", invoice),
            patch.object(service, "get_standalone_payment", status),
        ):
            run = await service.create_run(self.player, False)
            self.assertEqual(run["status"], "WAITING_PAYMENT")
            with self.assertRaises(HTTPException):
                await service.start_run(run["id"], self.player)
            self.stamp = 1700
            run = await service.reconcile(run)
            self.assertEqual(run["status"], "EXPIRED")
            payment.success = True
            await service.record_payment(payment)
            await service.record_payment(payment)
            row = await service.owned_run(run["id"], self.player)
            self.assertEqual(row["status"], "READY")
            entries = await crud.db.fetchall("SELECT * FROM satshole.financial_events")
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["amount"], 25)
            await service.start_run(run["id"], self.player)
            await service.record_payment(payment)
            self.assertEqual(
                (await service.owned_run(run["id"], self.player))["status"], "RUNNING"
            )

    async def test_server_replay_and_identical_retry(self):
        run = await self.free()
        started = await service.start_run(run["id"], self.player)
        self.stamp = 1010
        log = [[0, 100, 0]]
        result = await service.finish_run(
            run["id"], self.player, started["run_token"], log
        )
        self.assertEqual(result["status"], "VERIFIED")
        self.assertIsInstance(result["authoritative_score"], int)
        self.assertEqual(
            result,
            await service.finish_run(run["id"], self.player, started["run_token"], log),
        )
        with self.assertRaises(HTTPException):
            await service.finish_run(
                run["id"], self.player, started["run_token"], [[0, 0, 100]]
            )
        with self.assertRaises(HTTPException):
            await service.finish_run(run["id"], self.other, started["run_token"], log)
        with self.assertRaises(HTTPException):
            await service.finish_run(run["id"], self.player, "forged", log)

    async def test_operational_retry_retains_input_commitment(self):
        run = await self.free()
        started = await service.start_run(run["id"], self.player)
        self.stamp = 1010

        async def unavailable(*args):
            raise RuntimeError("busy")

        with patch.object(service, "verify", unavailable):
            with self.assertRaises(HTTPException):
                await service.finish_run(
                    run["id"], self.player, started["run_token"], [[0, 100, 0]]
                )
        row = await service.owned_run(run["id"], self.player)
        self.assertEqual(row["status"], "FINISHED_UNVERIFIED")
        with self.assertRaises(HTTPException):
            await service.finish_run(
                run["id"], self.player, started["run_token"], [[0, 0, 100]]
            )
        result = await service.finish_run(
            run["id"], self.player, started["run_token"], [[0, 100, 0]]
        )
        self.assertEqual(result["status"], "VERIFIED")

    async def test_settings_snapshot_and_pause(self):
        wallet = types.SimpleNamespace(
            wallet=types.SimpleNamespace(id="wallet", user="owner")
        )
        run = await self.free()
        config = api.GameSettings(duration=30, enabled=False, game_price=50)
        await api.save_settings(config, wallet)
        self.assertEqual((await service.game_config())["game_price"], 50)
        self.assertEqual(
            json.loads((await service.owned_run(run["id"], self.player))["config"])[
                "duration"
            ],
            10,
        )
        with self.assertRaises(HTTPException):
            await self.free()
        # Paid/ready attempts retain their purchased rules after pause.
        started = await service.start_run(run["id"], self.player)
        self.assertEqual(started["config"]["duration"], 10)

    async def test_receipt_recovers_interrupted_invoice_binding(self):
        payment = types.SimpleNamespace(
            payment_hash="orphan",
            bolt11="lnbc-test",
            wallet_id="wallet",
            amount=25000,
            success=True,
            extra={"tag": "satshole_game"},
        )

        async def invoice(**kwargs):
            payment.extra["run_id"] = kwargs["extra"]["run_id"]
            await service.record_payment(payment)
            return payment

        with patch.object(service, "create_invoice", invoice):
            run = await service.create_run(self.player, False)
        self.assertEqual(run["status"], "READY")
        self.assertEqual(run["paid"], 1)
        self.assertEqual(
            len(await crud.db.fetchall("SELECT * FROM satshole.financial_events")), 1
        )

    async def test_http_security_boundary(self):
        app = FastAPI()
        app.include_router(api.router, prefix="/satshole")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://test"
        ) as client:
            self.assertEqual(
                (
                    await client.post("/satshole/api/v1/game/runs", json={"free": True})
                ).status_code,
                401,
            )
            session = await client.post("/satshole/api/v1/game/session", json={})
            self.assertEqual(session.status_code, 200)
            self.assertIn("HttpOnly", session.headers["set-cookie"])
            self.assertIn("Secure", session.headers["set-cookie"])
            result = await client.post(
                "/satshole/api/v1/game/runs", json={"free": True}
            )
            self.assertEqual(result.status_code, 200)
            self.assertNotIn("seed", result.json())
            run = result.json()["id"]
            response = await client.post(
                f"/satshole/api/v1/game/runs/{run}/finish",
                json={"run_token": "x" * 40, "inputs": [], "score": 999999},
            )
            self.assertEqual(response.status_code, 422)
            response = await client.post(
                "/satshole/api/v1/game/runs",
                json={"free": True},
                headers={"Origin": "https://evil.example"},
            )
            self.assertEqual(response.status_code, 403)
            self.assertNotEqual(
                (await client.get("/satshole/api/v1/game/settings")).status_code, 200
            )


if __name__ == "__main__":
    unittest.main()
