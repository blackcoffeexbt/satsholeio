# Description: Add your page endpoints here.

from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from lnbits.core.models import User
from lnbits.decorators import check_user_exists
from lnbits.helpers import template_renderer
from lnbits.settings import settings

from .crud import get_satshole
from .helpers import lnurler

satshole_generic_router = APIRouter()


def satshole_renderer():
    return template_renderer(["satshole/templates"])


#######################################
##### ADD YOUR PAGE ENDPOINTS HERE ####
#######################################


# Backend admin page


@satshole_generic_router.get("/", response_class=HTMLResponse)
async def index(req: Request, user: User = Depends(check_user_exists)):
    return satshole_renderer().TemplateResponse(
        "satshole/index.html", {"request": req, "user": user.json()}
    )


# Frontend shareable page


@satshole_generic_router.get("/{satshole_id}")
async def satshole(req: Request, satshole_id):
    myex = await get_satshole(satshole_id)
    if not myex:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="SatsHole does not exist."
        )
    return satshole_renderer().TemplateResponse(
        "satshole/satshole.html",
        {
            "request": req,
            "satshole_id": satshole_id,
            "lnurlpay": lnurler(myex.id, "satshole.api_lnurl_pay", req),
            "web_manifest": f"/satshole/manifest/{satshole_id}.webmanifest",
        },
    )


# Manifest for public page, customise or remove manifest completely


@satshole_generic_router.get("/manifest/{satshole_id}.webmanifest")
async def manifest(satshole_id: str):
    satshole = await get_satshole(satshole_id)
    if not satshole:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="SatsHole does not exist."
        )

    return {
        "short_name": settings.lnbits_site_title,
        "name": satshole.name + " - " + settings.lnbits_site_title,
        "icons": [
            {
                "src": (
                    settings.lnbits_custom_logo
                    if settings.lnbits_custom_logo
                    else "https://cdn.jsdelivr.net/gh/lnbits/lnbits@0.3.0/docs/logos/lnbits.png"
                ),
                "type": "image/png",
                "sizes": "900x900",
            }
        ],
        "start_url": "/satshole/" + satshole_id,
        "background_color": "#1F2234",
        "description": "Minimal extension to build on",
        "display": "standalone",
        "scope": "/satshole/" + satshole_id,
        "theme_color": "#1F2234",
        "shortcuts": [
            {
                "name": satshole.name + " - " + settings.lnbits_site_title,
                "short_name": satshole.name,
                "description": satshole.name + " - " + settings.lnbits_site_title,
                "url": "/satshole/" + satshole_id,
            }
        ],
    }
