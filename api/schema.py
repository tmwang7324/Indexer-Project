"""GraphQL schema: Block, Transaction, Message."""
from datetime import timezone
from typing import Optional

import strawberry
from strawberry.scalars import JSON

from . import db


def _iso(dt) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@strawberry.type
class Coin:
    denom: str
    amount: str


@strawberry.type
class Message:
    index: int
    type: str
    raw: JSON


@strawberry.type
class Transaction:
    hash: str
    chain_id: str
    height: int
    index: int
    memo: str
    gas_limit: Optional[str]
    time: str
    fee: list[Coin]
    _tx_id: strawberry.Private[int]

    @strawberry.field
    async def messages(self) -> list[Message]:
        rows = await db.fetch(
            "SELECT msg_index, type, raw FROM messages WHERE tx_id = %s ORDER BY msg_index", (self._tx_id,))
        return [Message(index=r["msg_index"], type=r["type"], raw=r["raw"]) for r in rows]

    @classmethod
    def from_row(cls, r) -> "Transaction":
        fee = (r["tx_info"].get("auth_info", {}).get("fee", {}).get("amount")) or []
        return cls(
            hash=r["tx_hash"], chain_id=r["chain_id"], height=r["height"], index=r["tx_index"],
            memo=r["memo"], gas_limit=None if r["gas_limit"] is None else str(r["gas_limit"]),
            time=_iso(r["created_at"]), fee=[Coin(denom=c["denom"], amount=c["amount"]) for c in fee],
            _tx_id=r["tx_id"],
        )


TX_COLUMNS = "tx_id, tx_hash, chain_id, height, tx_index, memo, gas_limit, created_at, tx_info"


@strawberry.type
class Block:
    chain_id: str
    height: int
    hash: str
    time: str
    tx_count: int
    _block_id: strawberry.Private[int]

    @strawberry.field
    async def transactions(self) -> list[Transaction]:
        rows = await db.fetch(
            f"SELECT {TX_COLUMNS} FROM transactions WHERE block_id = %s ORDER BY tx_index", (self._block_id,))
        return [Transaction.from_row(r) for r in rows]


@strawberry.type
class Query:
    @strawberry.field
    async def block(self, chain_id: str, height: int) -> Optional[Block]:
        r = await db.fetch_one(
            "SELECT block_id, chain_id, height, block_hash, tx_num, created_at FROM blocks "
            "WHERE chain_id = %s AND height = %s", (chain_id, height))
        if r is None:
            return None
        return Block(chain_id=r["chain_id"], height=r["height"], hash=r["block_hash"],
                     time=_iso(r["created_at"]), tx_count=r["tx_num"], _block_id=r["block_id"])

    @strawberry.field
    async def transaction(self, hash: str) -> Optional[Transaction]:
        r = await db.fetch_one(f"SELECT {TX_COLUMNS} FROM transactions WHERE tx_hash = %s", (hash.upper(),))
        return None if r is None else Transaction.from_row(r)


schema = strawberry.Schema(query=Query)
