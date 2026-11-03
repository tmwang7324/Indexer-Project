"""Verification (D14).

1. Count rules: before a block commits, what the writer stored is compared with what the source said.
   `check_counts` is a pure function; `written_summary` asks the open transaction what it wrote.
2. The sampled `verify` command: re-read stored blocks from the source and compare every stored field.
"""
import json
import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from psycopg2.extras import RealDictCursor

from .handlers import Registry, get_registry
from .models import Block


# --- count rules -------------------------------------------------------------------------------
@dataclass(frozen=True)
class Summary:
    transactions: int
    outcomes: int        # transactions that have an outcome (a source without /block_results has none)
    messages: int


@dataclass(frozen=True)
class Mismatch:
    what: str
    expected: int
    actual: int

    def __str__(self) -> str:
        return f"{self.what}: the source has {self.expected}, the database has {self.actual}"


def source_summary(block: Block) -> Summary:
    return Summary(
        transactions=block.tx_num,
        outcomes=sum(1 for tx in block.transactions if tx.outcome is not None),
        messages=sum(len(tx.messages) for tx in block.transactions),
    )


def written_summary(cur, block_id: int) -> Summary:
    """What the open transaction holds for this block."""
    cur.execute(
        """SELECT count(*), count(code),
                  (SELECT count(*) FROM messages m JOIN transactions t2 USING (tx_id) WHERE t2.block_id = %s)
           FROM transactions WHERE block_id = %s""", (block_id, block_id))
    return Summary(*cur.fetchone())


def check_counts(source: Summary, written: Summary) -> list:
    """Every disagreement between the source and the database, as `Mismatch` objects (empty = fine)."""
    pairs = [("transactions", source.transactions, written.transactions),
             ("outcomes", source.outcomes, written.outcomes),
             ("messages", source.messages, written.messages)]
    return [Mismatch(what, expected, actual) for what, expected, actual in pairs if expected != actual]


# --- the sampled verify command ----------------------------------------------------------------
@dataclass(frozen=True)
class Difference:
    height: int
    table: str           # "transactions[0]", "messages[1.0]", ...
    column: str
    stored: object
    source: object

    def __str__(self) -> str:
        return f"{self.height} / {self.table} / {self.column}: {self.stored!r} != {self.source!r}"


_FRACTION = re.compile(r"\.(\d+)")


def _parse_time(value: str) -> datetime:
    """The node reports nanoseconds; PostgreSQL stores microseconds and ROUNDS the nanoseconds (half up),
    it does not truncate them. Do the same, or every other timestamp would look different."""
    nanos = [0]

    def take(match):
        nanos[0] = int(match.group(1)[:9].ljust(9, "0"))
        return ""

    whole = datetime.fromisoformat(_FRACTION.sub(take, value).replace("Z", "+00:00")).astimezone(timezone.utc)
    return whole + timedelta(microseconds=(nanos[0] + 500) // 1000)


def _canonical(value):
    """A comparable form of a value, whichever side it came from."""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if isinstance(value, (Decimal, int)) and not isinstance(value, bool):
        return Decimal(value)
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    return value


def _like(expected, stored):
    """The source value converted to the type the database column has, so '12' and 12 compare equal."""
    if expected is None:
        return None
    if isinstance(stored, datetime) and isinstance(expected, str):
        return _parse_time(expected)
    if isinstance(stored, (Decimal, int)) and not isinstance(stored, bool) and isinstance(expected, (str, int)):
        try:
            return Decimal(expected)
        except ArithmeticError:
            return expected
    return expected


def _expected(block: Block, registry: Registry) -> dict:
    """The rows the writer should have stored for this block: {(table, key): {column: value}}."""
    rows = {("blocks", ""): {"block_hash": block.hash, "tx_num": block.tx_num, "created_at": block.time}}
    for tx in block.transactions:
        o = tx.outcome
        rows[("transactions", str(tx.index))] = {
            "tx_hash": tx.hash, "memo": tx.memo, "gas_limit": tx.gas_limit, "created_at": block.time,
            "tx_info": tx.info,
            "code": o and o.code, "codespace": o and o.codespace, "gas_wanted": o and o.gas_wanted,
            "gas_used": o and o.gas_used, "log": o and o.log, "events": o and o.events}
        for i, coin in enumerate(tx.fee):
            rows[("transaction_fees", f"{tx.index}.{i}")] = {"denom": coin["denom"], "amount": coin["amount"]}
        for msg in tx.messages:
            key = f"{tx.index}.{msg.index}"
            rows[("messages", key)] = {"type": msg.type, "raw": msg.raw}
            result = registry.handle(msg.type, msg.raw)
            if result is None:
                continue
            rows[(result.table, key)] = dict(result.row)
            for table, child in result.children:
                rows.setdefault((table, key), {"rows": []})["rows"].append(child)
            rows[("message_addresses", key)] = {"addresses": sorted(f"{role}:{a}" for role, a in result.addresses)}
    return rows


def _stored(cur, chain_id: str, height: int, registry: Registry) -> dict:
    """The same shape as `_expected`, read from the database."""
    cur.execute("SELECT block_id, block_hash, tx_num, created_at FROM blocks WHERE chain_id = %s AND height = %s",
                (chain_id, height))
    row = cur.fetchone()
    if row is None:
        return {}
    block_id = row.pop("block_id")
    rows = {("blocks", ""): dict(row)}
    cur.execute("SELECT * FROM transactions WHERE block_id = %s", (block_id,))
    tx_ids = {}
    for r in cur.fetchall():
        tx_ids[r["tx_id"]] = r["tx_index"]
        rows[("transactions", str(r["tx_index"]))] = {
            k: v for k, v in r.items() if k not in ("tx_id", "block_id", "chain_id", "height", "tx_index")}
    cur.execute("SELECT * FROM transaction_fees WHERE tx_id = ANY(%s)", (list(tx_ids),))
    for r in cur.fetchall():
        rows[("transaction_fees", f"{tx_ids[r['tx_id']]}.{r['coin_index']}")] = {
            "denom": r["denom"], "amount": r["amount"]}
    cur.execute("SELECT * FROM messages WHERE tx_id = ANY(%s)", (list(tx_ids),))
    keys = {}
    for r in cur.fetchall():
        keys[r["message_id"]] = f"{tx_ids[r['tx_id']]}.{r['msg_index']}"
        rows[("messages", keys[r["message_id"]])] = {"type": r["type"], "raw": r["raw"]}
    ids = list(keys)
    handlers = {h.name: h for h in (registry.get(v["type"]) for (t, _), v in rows.items() if t == "messages") if h}
    for handler in handlers.values():
        for table in (handler.table, *handler.side_tables):
            cur.execute(f"SELECT * FROM {table} WHERE message_id = ANY(%s)", (ids,))
            for r in cur.fetchall():
                key = keys[r.pop("message_id")]
                if table == handler.table:
                    rows[(table, key)] = r
                else:
                    rows.setdefault((table, key), {"rows": []})["rows"].append(r)
    cur.execute("""SELECT ma.message_id, a.value, ma.role FROM message_addresses ma
                   JOIN address a USING (address_id) WHERE ma.message_id = ANY(%s)""", (ids,))
    for r in cur.fetchall():
        rows.setdefault(("message_addresses", keys[r["message_id"]]), {"addresses": []})["addresses"].append(
            f"{r['role']}:{r['value']}")
    for (table, _), row in rows.items():
        if table == "message_addresses":
            row["addresses"].sort()
    return rows


def _children_key(rows: list) -> list:
    return sorted(json.dumps(_canonical_json(r), sort_keys=True, default=str) for r in rows)


def _canonical_json(row: dict) -> dict:
    return {k: (str(v) if isinstance(v, (Decimal, datetime)) else v) for k, v in row.items()}


def diff_block(conn, block: Block, registry: Optional[Registry] = None) -> list:
    """Every difference between the stored rows of `block.height` and what the source says."""
    registry = registry or get_registry()
    expected = _expected(block, registry)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        stored = _stored(cur, block.chain_id, block.height, registry)
    found = []

    def label(table, key):
        return f"{table}[{key}]" if key else table

    for ident in sorted(set(stored) | set(expected)):
        table, key = ident
        if ident not in stored or ident not in expected:
            found.append(Difference(block.height, label(table, key), "<row>",
                                    "present" if ident in stored else "missing",
                                    "present" if ident in expected else "missing"))
            continue
        have, want = stored[ident], expected[ident]
        for column in sorted(set(have) | set(want)):
            if column == "rows":
                a, b = _children_key(have["rows"]), _children_key(want["rows"])
            else:
                a, b = have.get(column), want.get(column)
                b = _like(b, a)
                a, b = _canonical(a), _canonical(b)
            if a != b:
                found.append(Difference(block.height, label(table, key), column, a, b))
    return found


def pick_sample(heights: list, n: int, seed: int) -> list:
    """N of the stored (chain_id, height) pairs, chosen with a seeded generator so a run can be repeated."""
    return sorted(random.Random(seed).sample(sorted(heights), min(n, len(heights))))
