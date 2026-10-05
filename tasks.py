import asyncio

from lnbits.core.models import Payment
from lnbits.core.services import websocket_updater
from lnbits.tasks import register_invoice_listener

from .crud import get_satshole, update_satshole
from .models import CreateSatsHoleData

#######################################
########## RUN YOUR TASKS HERE ########
#######################################

# The usual task is to listen to invoices related to this extension


async def wait_for_paid_invoices():
    invoice_queue = asyncio.Queue()
    register_invoice_listener(invoice_queue, "ext_satshole")
    while True:
        payment = await invoice_queue.get()
        await on_invoice_paid(payment)


# Do somethhing when an invoice related top this extension is paid


async def on_invoice_paid(payment: Payment) -> None:
    if payment.extra.get("tag") != "SatsHole":
        return

    satshole_id = payment.extra.get("satsholeId")
    assert satshole_id, "satsholeId not set in invoice"
    satshole = await get_satshole(satshole_id)
    assert satshole, "SatsHole does not exist"

    # update something in the db
    if payment.extra.get("lnurlwithdraw"):
        total = satshole.total - payment.amount
    else:
        total = satshole.total + payment.amount

    satshole.total = total
    await update_satshole(CreateSatsHoleData(**satshole.dict()))

    # here we could send some data to a websocket on
    # wss://<your-lnbits>/api/v1/ws/<satshole_id> and then listen to it on

    some_payment_data = {
        "name": satshole.name,
        "amount": payment.amount,
        "fee": payment.fee,
        "checking_id": payment.checking_id,
    }

    await websocket_updater(satshole_id, str(some_payment_data))
