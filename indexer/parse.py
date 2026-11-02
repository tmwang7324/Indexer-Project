"""Parse a block once into Block / Transaction / Message objects."""
import base64
import binascii
import hashlib

from .errors import BadDataError
from .models import Block, Message, Transaction


def tx_hash(raw_b64: str) -> str:
    """SHA-256 of the raw transaction bytes, uppercase hex (as `hash_to_hex` does)."""
    try:
        data = base64.b64decode(raw_b64, validate=True)
    except (binascii.Error, ValueError, TypeError) as exc:
        raise BadDataError(f"transaction bytes are not valid base64: {exc}") from exc
    return hashlib.sha256(data).hexdigest().upper()


def block_hash_hex(hash_b64: str) -> str:
    try:
        return base64.b64decode(hash_b64, validate=True).hex().upper()
    except (binascii.Error, ValueError, TypeError) as exc:
        raise BadDataError(f"block hash is not valid base64: {exc}") from exc


def _parse_transaction(index: int, raw_b64: str, info: dict) -> Transaction:
    try:
        body = info["body"]
        fee = info["auth_info"]["fee"]
        messages = [Message(i, m["@type"], m) for i, m in enumerate(body["messages"])]
        gas_limit = fee.get("gas_limit")
        return Transaction(
            index=index,
            hash=tx_hash(raw_b64),
            memo=body.get("memo") or "",
            gas_limit=int(gas_limit) if gas_limit not in (None, "") else None,
            fee=list(fee.get("amount") or []),
            info=info,
            messages=messages,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise BadDataError(f"transaction {index} is malformed: {exc!r}") from exc


def parse_block(block_id: dict, block: dict, tx_infos: list) -> Block:
    """Build a Block from a node's `block_id` / `block` and the decoded transactions.

    `tx_infos` are the decoded transactions ({"body", "auth_info", "signatures"}),
    in the same order as the raw bytes in `block.data.txs`.
    """
    try:
        header = block["header"]
        raw_txs = block["data"].get("txs") or []
        chain_id, height, time = header["chain_id"], int(header["height"]), header["time"]
        hash_b64 = block_id["hash"]
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise BadDataError(f"block header is malformed: {exc!r}") from exc
    if len(raw_txs) != len(tx_infos):
        raise BadDataError(
            f"block {chain_id}/{height} has {len(raw_txs)} raw transactions "
            f"but {len(tx_infos)} decoded ones"
        )
    transactions = [_parse_transaction(i, raw, info) for i, (raw, info) in enumerate(zip(raw_txs, tx_infos))]
    return Block(chain_id, height, block_hash_hex(hash_b64), time, transactions)
