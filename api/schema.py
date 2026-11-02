"""GraphQL schema: Block, Transaction, Message."""
from datetime import timezone
from typing import Optional

import strawberry
from strawberry.scalars import JSON

from indexer.handlers import get_registry

from . import db


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(w.capitalize() for w in rest)


async def _details(message_id: int, type_url: str):
    """The typed row of a message (columns as camelCase keys), or None for a type without a handler."""
    handler = get_registry().get(type_url)
    if handler is None:
        return None
    row = await db.fetch_one(
        f"SELECT to_jsonb(t) - 'message_id' AS d FROM {handler.table} t WHERE message_id = %s", (message_id,))
    if row is None:
        return None
    details = {_camel(k): v for k, v in row["d"].items()}
    for side in handler.side_tables:
        rows = await db.fetch(f"SELECT to_jsonb(s) - 'message_id' AS d FROM {side} s WHERE message_id = %s "
                              f"ORDER BY 1", (message_id,))
        details[_camel(side.split("_", 2)[-1])] = [{_camel(k): v for k, v in r["d"].items()} for r in rows]
    return details


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
    _message_id: strawberry.Private[int]
    _tx_id: strawberry.Private[int]

    @strawberry.field(description="The typed row for this message's type (null when the type has no handler).")
    async def details(self) -> Optional[JSON]:
        return await _details(self._message_id, self.type)

    @strawberry.field
    async def transaction(self) -> "Transaction":
        r = await db.fetch_one(f"SELECT {TX_COLUMNS} FROM transactions WHERE tx_id = %s", (self._tx_id,))
        return Transaction.from_row(r)

    @classmethod
    def from_row(cls, r) -> "Message":
        return cls(index=r["msg_index"], type=r["type"], raw=r["raw"], _message_id=r["message_id"],
                   _tx_id=r["tx_id"])


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
            "SELECT message_id, tx_id, msg_index, type, raw FROM messages WHERE tx_id = %s ORDER BY msg_index",
            (self._tx_id,))
        return [Message.from_row(r) for r in rows]

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


MAX_LIMIT = 1000


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


    @strawberry.field(description="Messages of one type, oldest first. Cursor paging replaces `limit` later.")
    async def messages(self, type: str, chain_id: Optional[str] = None, limit: int = 100) -> list[Message]:
        rows = await db.fetch(
            """SELECT m.message_id, m.tx_id, m.msg_index, m.type, m.raw
               FROM messages m JOIN transactions t ON t.tx_id = m.tx_id
               WHERE m.type = %s AND (%s::text IS NULL OR t.chain_id = %s)
               ORDER BY t.height, t.tx_index, m.msg_index LIMIT %s""",
            (type, chain_id, chain_id, max(0, min(limit, MAX_LIMIT))))
        return [Message.from_row(r) for r in rows]


schema = strawberry.Schema(query=Query)
