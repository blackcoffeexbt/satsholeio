# Description: This file contains the extensions API endpoints.

from http import HTTPStatus

from fastapi import APIRouter, Depends, Request
from lnbits.core.crud import get_user
from lnbits.core.models import WalletTypeInfo
from lnbits.core.services import create_invoice
from lnbits.decorators import require_admin_key, require_invoice_key
from starlette.exceptions import HTTPException

from .crud import (
    create_satshole,
    delete_satshole,
    get_satshole,
    get_satsholes,
    update_satshole,
)
from .helpers import lnurler
from .models import CreateSatsHoleData, CreatePayment, SatsHole

satshole_api_router = APIRouter()

# Note: we add the lnurl params to returns so the links
# are generated in the SatsHole model in models.py

## Get all the records belonging to the user


@satshole_api_router.get("/api/v1/myex")
async def api_satsholes(
    req: Request,  # Withoutthe lnurl stuff this wouldnt be needed
    wallet: WalletTypeInfo = Depends(require_invoice_key),
) -> list[SatsHole]:
    wallet_ids = [wallet.wallet.id]
    user = await get_user(wallet.wallet.user)
    wallet_ids = user.wallet_ids if user else []
    satsholes = await get_satsholes(wallet_ids)

    # Populate lnurlpay and lnurlwithdraw for each instance.
    # Without the lnurl stuff this wouldnt be needed.
    for myex in satsholes:
        myex.lnurlpay = lnurler(myex.id, "satshole.api_lnurl_pay", req)
        myex.lnurlwithdraw = lnurler(myex.id, "satshole.api_lnurl_withdraw", req)

    return satsholes


## Get a single record


@satshole_api_router.get(
    "/api/v1/myex/{satshole_id}",
    dependencies=[Depends(require_invoice_key)],
)
async def api_satshole(satshole_id: str, req: Request) -> SatsHole:
    myex = await get_satshole(satshole_id)
    if not myex:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="SatsHole does not exist."
        )
    # Populate lnurlpay and lnurlwithdraw.
    # Without the lnurl stuff this wouldnt be needed.
    myex.lnurlpay = lnurler(myex.id, "satshole.api_lnurl_pay", req)
    myex.lnurlwithdraw = lnurler(myex.id, "satshole.api_lnurl_withdraw", req)

    return myex


## Create a new record


@satshole_api_router.post("/api/v1/myex", status_code=HTTPStatus.CREATED)
async def api_satshole_create(
    req: Request,  # Withoutthe lnurl stuff this wouldnt be needed
    data: CreateSatsHoleData,
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> SatsHole:
    myex = await create_satshole(data)

    # Populate lnurlpay and lnurlwithdraw.
    # Withoutthe lnurl stuff this wouldnt be needed.
    myex.lnurlpay = lnurler(myex.id, "satshole.api_lnurl_pay", req)
    myex.lnurlwithdraw = lnurler(myex.id, "satshole.api_lnurl_withdraw", req)

    return myex


## update a record


@satshole_api_router.put("/api/v1/myex/{satshole_id}")
async def api_satshole_update(
    req: Request,  # Withoutthe lnurl stuff this wouldnt be needed
    data: CreateSatsHoleData,
    satshole_id: str,
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> SatsHole:
    myex = await get_satshole(satshole_id)
    if not myex:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="SatsHole does not exist."
        )

    if wallet.wallet.id != myex.wallet:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail="Not your SatsHole."
        )

    for key, value in data.dict().items():
        setattr(myex, key, value)

    myex = await update_satshole(data)

    # Populate lnurlpay and lnurlwithdraw.
    # Without the lnurl stuff this wouldnt be needed.
    myex.lnurlpay = lnurler(myex.id, "satshole.api_lnurl_pay", req)
    myex.lnurlwithdraw = lnurler(myex.id, "satshole.api_lnurl_withdraw", req)

    return myex


## Delete a record


@satshole_api_router.delete("/api/v1/myex/{satshole_id}")
async def api_satshole_delete(
    satshole_id: str, wallet: WalletTypeInfo = Depends(require_admin_key)
):
    myex = await get_satshole(satshole_id)

    if not myex:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="SatsHole does not exist."
        )

    if myex.wallet != wallet.wallet.id:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail="Not your SatsHole."
        )

    await delete_satshole(satshole_id)
    return


# ANY OTHER ENDPOINTS YOU NEED

## This endpoint creates a payment


@satshole_api_router.post("/api/v1/myex/payment", status_code=HTTPStatus.CREATED)
async def api_satshole_create_invoice(data: CreatePayment) -> dict:
    satshole = await get_satshole(data.satshole_id)

    if not satshole:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="SatsHole does not exist."
        )

    # we create a payment and add some tags,
    # so tasks.py can grab the payment once its paid

    payment = await create_invoice(
        wallet_id=satshole.wallet,
        amount=data.amount,
        memo=(
            f"{data.memo} to {satshole.name}" if data.memo else f"{satshole.name}"
        ),
        extra={
            "tag": "satshole",
            "amount": data.amount,
        },
    )

    return {"payment_hash": payment.payment_hash, "payment_request": payment.bolt11}
