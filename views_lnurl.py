# Description: Extensions that use LNURL usually have a few endpoints in views_lnurl.py.

from http import HTTPStatus

import shortuuid
from fastapi import APIRouter, Query, Request
from lnbits.core.services import create_invoice, pay_invoice
from loguru import logger

from .crud import get_satshole

#################################################
########### A very simple LNURLpay ##############
# https://github.com/lnurl/luds/blob/luds/06.md #
#################################################
#################################################

satshole_lnurl_router = APIRouter()


@satshole_lnurl_router.get(
    "/api/v1/lnurl/pay/{satshole_id}",
    status_code=HTTPStatus.OK,
    name="satshole.api_lnurl_pay",
)
async def api_lnurl_pay(
    request: Request,
    satshole_id: str,
):
    satshole = await get_satshole(satshole_id)
    if not satshole:
        return {"status": "ERROR", "reason": "No satshole found"}
    return {
        "callback": str(
            request.url_for(
                "satshole.api_lnurl_pay_callback", satshole_id=satshole_id
            )
        ),
        "maxSendable": satshole.lnurlpayamount * 1000,
        "minSendable": satshole.lnurlpayamount * 1000,
        "metadata": '[["text/plain", "' + satshole.name + '"]]',
        "tag": "payRequest",
    }


@satshole_lnurl_router.get(
    "/api/v1/lnurl/paycb/{satshole_id}",
    status_code=HTTPStatus.OK,
    name="satshole.api_lnurl_pay_callback",
)
async def api_lnurl_pay_cb(
    request: Request,
    satshole_id: str,
    amount: int = Query(...),
):
    satshole = await get_satshole(satshole_id)
    logger.debug(satshole)
    if not satshole:
        return {"status": "ERROR", "reason": "No satshole found"}

    payment = await create_invoice(
        wallet_id=satshole.wallet,
        amount=int(amount / 1000),
        memo=satshole.name,
        unhashed_description=f'[["text/plain", "{satshole.name}"]]'.encode(),
        extra={
            "tag": "SatsHole",
            "satsholeId": satshole_id,
            "extra": request.query_params.get("amount"),
        },
    )
    return {
        "pr": payment.bolt11,
        "routes": [],
        "successAction": {"tag": "message", "message": f"Paid {satshole.name}"},
    }


#################################################
######## A very simple LNURLwithdraw ############
# https://github.com/lnurl/luds/blob/luds/03.md #
#################################################
## withdraw is unlimited, look at withdraw ext ##
## for more advanced withdraw options          ##
#################################################


@satshole_lnurl_router.get(
    "/api/v1/lnurl/withdraw/{satshole_id}",
    status_code=HTTPStatus.OK,
    name="satshole.api_lnurl_withdraw",
)
async def api_lnurl_withdraw(
    request: Request,
    satshole_id: str,
):
    satshole = await get_satshole(satshole_id)
    if not satshole:
        return {"status": "ERROR", "reason": "No satshole found"}
    k1 = shortuuid.uuid(name=satshole.id)
    return {
        "tag": "withdrawRequest",
        "callback": str(
            request.url_for(
                "satshole.api_lnurl_withdraw_callback", satshole_id=satshole_id
            )
        ),
        "k1": k1,
        "defaultDescription": satshole.name,
        "maxWithdrawable": satshole.lnurlwithdrawamount * 1000,
        "minWithdrawable": satshole.lnurlwithdrawamount * 1000,
    }


@satshole_lnurl_router.get(
    "/api/v1/lnurl/withdrawcb/{satshole_id}",
    status_code=HTTPStatus.OK,
    name="satshole.api_lnurl_withdraw_callback",
)
async def api_lnurl_withdraw_cb(
    satshole_id: str,
    pr: str | None = None,
    k1: str | None = None,
):
    assert k1, "k1 is required"
    assert pr, "pr is required"
    satshole = await get_satshole(satshole_id)
    if not satshole:
        return {"status": "ERROR", "reason": "No satshole found"}

    k1_check = shortuuid.uuid(name=satshole.id)
    if k1_check != k1:
        return {"status": "ERROR", "reason": "Wrong k1 check provided"}

    await pay_invoice(
        wallet_id=satshole.wallet,
        payment_request=pr,
        max_sat=int(satshole.lnurlwithdrawamount * 1000),
        extra={
            "tag": "SatsHole",
            "satsholeId": satshole_id,
            "lnurlwithdraw": True,
        },
    )
    return {"status": "OK"}
