import asyncio

from lnbits.tasks import register_invoice_listener
from loguru import logger

from .competitions import record_entry_payment
from .crud import db
from .game_service import record_payment
from .moderation import recover
from .settlement import maintenance


async def wait_for_paid_invoices():
    # Recover an interrupted verifier without permitting a different input payload.
    await db.execute(
        "UPDATE satshole.runs SET status='FINISHED_UNVERIFIED' WHERE status='VERIFYING'"
    )
    await db.execute(
        "UPDATE satshole.entry_invoices SET status='CREATED' WHERE status='INVOICING'"
    )
    await recover()
    invoice_queue = asyncio.Queue()
    register_invoice_listener(invoice_queue, "ext_satshole")
    while True:
        try:
            payment = await asyncio.wait_for(invoice_queue.get(), timeout=30)
        except asyncio.TimeoutError:
            try:
                await maintenance()
            except Exception:
                logger.warning("SatsHole settlement maintenance will retry.")
            continue
        try:
            await record_payment(payment)
            await record_entry_payment(payment)
        except Exception:
            logger.warning(
                "SatsHole receipt processing failed; status reconciliation will retry."
            )


async def on_invoice_paid(payment):
    await record_payment(payment)
    await record_entry_payment(payment)
