# Description: This file contains the CRUD operations for talking to the database.


from lnbits.db import Database
from lnbits.helpers import urlsafe_short_hash

from .models import CreateSatsHoleData, SatsHole

db = Database("ext_satshole")


async def create_satshole(data: CreateSatsHoleData) -> SatsHole:
    data.id = urlsafe_short_hash()
    await db.insert("satshole.maintable", data)
    return SatsHole(**data.dict())


async def get_satshole(satshole_id: str) -> SatsHole | None:
    return await db.fetchone(
        "SELECT * FROM satshole.maintable WHERE id = :id",
        {"id": satshole_id},
        SatsHole,
    )


async def get_satsholes(wallet_ids: str | list[str]) -> list[SatsHole]:
    if isinstance(wallet_ids, str):
        wallet_ids = [wallet_ids]
    q = ",".join([f"'{w}'" for w in wallet_ids])
    return await db.fetchall(
        f"SELECT * FROM satshole.maintable WHERE wallet IN ({q}) ORDER BY id",
        model=SatsHole,
    )


async def update_satshole(data: CreateSatsHoleData) -> SatsHole:
    await db.update("satshole.maintable", data)
    return SatsHole(**data.dict())


async def delete_satshole(satshole_id: str) -> None:
    await db.execute(
        "DELETE FROM satshole.maintable WHERE id = :id", {"id": satshole_id}
    )
