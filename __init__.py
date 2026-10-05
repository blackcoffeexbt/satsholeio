import asyncio

from fastapi import APIRouter
from lnbits.tasks import create_permanent_unique_task
from loguru import logger

from .crud import db
from .tasks import wait_for_paid_invoices
from .views import satshole_generic_router
from .views_api import satshole_api_router
from .views_lnurl import satshole_lnurl_router

logger.debug(
    "This logged message is from satshole/__init__.py, you can debug in your "
    "extension using 'import logger from loguru' and 'logger.debug(<thing-to-log>)'."
)


satshole_ext: APIRouter = APIRouter(prefix="/satshole", tags=["SatsHole"])
satshole_ext.include_router(satshole_generic_router)
satshole_ext.include_router(satshole_api_router)
satshole_ext.include_router(satshole_lnurl_router)

satshole_static_files = [
    {
        "path": "/satshole/static",
        "name": "satshole_static",
    }
]

scheduled_tasks: list[asyncio.Task] = []


def satshole_stop():
    for task in scheduled_tasks:
        try:
            task.cancel()
        except Exception as ex:
            logger.warning(ex)


def satshole_start():
    task = create_permanent_unique_task("ext_satshole", wait_for_paid_invoices)
    scheduled_tasks.append(task)


__all__ = [
    "db",
    "satshole_ext",
    "satshole_start",
    "satshole_static_files",
    "satshole_stop",
]
