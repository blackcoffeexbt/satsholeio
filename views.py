# Description: Add your page endpoints here.

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from lnbits.core.models import User
from lnbits.decorators import check_user_exists
from lnbits.helpers import template_renderer

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


@satshole_generic_router.get("/play", response_class=HTMLResponse)
async def play(req: Request):
    return satshole_renderer().TemplateResponse("satshole/play.html", {"request": req})
