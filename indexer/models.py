"""Plain data objects produced by the parser (one parse per block)."""
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class Message:
    index: int           # position inside the transaction, from 0
    type: str            # the "@type" URL
    raw: dict            # the message JSON as the node returned it


@dataclass(frozen=True)
class Outcome:
    code: int
    codespace: str
    gas_wanted: int
    gas_used: int
    log: str
    events: list


@dataclass(frozen=True)
class Transaction:
    index: int           # position inside the block, from 0
    hash: str            # SHA-256 of the raw bytes, uppercase hex
    memo: str
    gas_limit: Optional[int]
    fee: list            # [{"denom": ..., "amount": ...}, ...]
    info: dict           # {"body": ..., "auth_info": ..., "signatures": ...}
    messages: list = field(default_factory=list)
    outcome: Optional[Outcome] = None


@dataclass(frozen=True)
class Block:
    chain_id: str
    height: int
    hash: str            # uppercase hex
    time: str            # RFC 3339, as the node reports it
    transactions: list = field(default_factory=list)

    @property
    def tx_num(self) -> int:
        return len(self.transactions)


JsonDict = dict[str, Any]


@dataclass(frozen=True)
class WorkItem:
    """One block to index. `load` fetches and parses it (it may raise BadDataError or TransientError);
    the height is known before the block is loaded, so a failure can be recorded against it."""
    chain_id: str
    height: int
    load: Callable[[], Block]
