"""Parse a block once into Block / Transaction / Message objects."""
import base64
import binascii
import hashlib
from dataclasses import replace

from .errors import BadDataError
from .models import Block, Message, Outcome, Transaction


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


def _int(value, what: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise BadDataError(f"{what} is not an integer: {value!r}") from exc


def parse_outcome(result: dict) -> Outcome:
    """One entry of /block_results `txs_results`. The base64 `data` field is not stored (D6)."""
    try:
        return Outcome(
            code=_int(result.get("code", 0), "code"),
            codespace=result.get("codespace") or "",
            gas_wanted=_int(result.get("gas_wanted", 0), "gas_wanted"),
            gas_used=_int(result.get("gas_used", 0), "gas_used"),
            log=result.get("log") or "",
            events=result.get("events") or [],
        )
    except AttributeError as exc:
        raise BadDataError(f"transaction result is malformed: {result!r}") from exc


def match_outcomes(transactions: list, results: list) -> list:
    """Attach each result to the transaction at the same position (D4). Counts must agree."""
    if len(transactions) != len(results):
        raise BadDataError(
            f"{len(transactions)} transactions but {len(results)} results: the two responses disagree")
    return [replace(tx, outcome=parse_outcome(res)) for tx, res in zip(transactions, results)]


def parse_txs_block(pages: list, results_doc: dict) -> Block:
    """Build a Block from the `txs/block` response (all its pages) and the `block_results` response.

    The transactions arrive decoded, in the same order as the raw bytes in `block.data.txs`.
    """
    try:
        first = pages[0]
        tx_infos = [tx for page in pages for tx in (page.get("txs") or [])]
        block = parse_block(first["block_id"], first["block"], tx_infos)
        result = results_doc.get("result", results_doc)
        result_height = _int(result["height"], "block_results height")
        results = result.get("txs_results") or []
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise BadDataError(f"txs/block or block_results response is malformed: {exc!r}") from exc
    if result_height != block.height:
        raise BadDataError(f"block_results is for height {result_height}, the block is {block.height}")
    return replace(block, transactions=match_outcomes(block.transactions, results))


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
