"""Declarative handlers: a pure function from a message's JSON to its typed row(s).

A handler never opens a connection or writes anything. It returns a HandlerResult that the
writer inserts inside the block's transaction. Each handler also declares its address
fields and their roles explicitly (ticket 03): no guessing from key names.
"""
import base64
import binascii
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Union

Path = str                       # "a.b", "a.0.b" (list index) or "a[].b" (every element)
Column = Union[Path, Callable[[dict], Any]]


def values(obj: Any, path: Path) -> list:
    """Every value at `path`; missing keys and nulls give nothing."""
    current = [obj]
    for seg in path.split("."):
        wild = seg.endswith("[]")
        key = seg[:-2] if wild else seg
        nxt = []
        for o in current:
            if isinstance(o, dict):
                v = o.get(key)
            elif isinstance(o, list) and key.isdigit():
                v = o[int(key)] if int(key) < len(o) else None
            else:
                v = None
            if v is None:
                continue
            if wild:
                nxt.extend(v if isinstance(v, list) else [])
            else:
                nxt.append(v)
        current = nxt
    return current


def get(obj: Any, path: Path) -> Any:
    found = values(obj, path)
    return found[0] if found else None


def num(path: Path) -> Callable[[dict], Any]:
    """A numeric column: an empty string means 'no value', not zero."""
    def column(message: dict):
        v = get(message, path)
        return None if v == "" else v
    return column


def count(path: Path) -> Callable[[dict], Optional[int]]:
    def column(message: dict):
        v = get(message, path)
        return len(v) if isinstance(v, list) else None
    return column


def first_key(path: Path) -> Callable[[dict], Optional[str]]:
    """The first key of an embedded contract message, i.e. the action name ({"swap": {...}} -> swap)."""
    def column(message: dict):
        v = get(message, path)
        return next(iter(v), None) if isinstance(v, dict) else None
    return column


def decoded_size(path: Path) -> Callable[[dict], Optional[int]]:
    """Size in bytes of a base64 field. Big blobs stay only in messages.raw."""
    def column(message: dict):
        v = get(message, path)
        if not isinstance(v, str):
            return None
        try:
            return len(base64.b64decode(v))
        except (binascii.Error, ValueError):
            return None
    return column


@dataclass(frozen=True)
class HandlerResult:
    table: str
    row: dict                                   # column -> value, without message_id
    children: list = field(default_factory=list)    # [(side table, row)], without message_id
    addresses: list = field(default_factory=list)   # [(role, address)] in declaration order


@dataclass(frozen=True)
class Handler:
    name: str                                   # the value in type.json
    type_url: str
    table: str
    columns: dict                               # column -> Column
    addresses: tuple = ()                       # ((role, Path), ...)
    children: Optional[Callable[[dict], list]] = None
    side_tables: tuple = ()                     # side tables this handler writes to

    def __call__(self, message: dict) -> HandlerResult:
        row = {col: (src(message) if callable(src) else get(message, src)) for col, src in self.columns.items()}
        children = self.children(message) if self.children else []
        addresses = [(role, a) for role, path in self.addresses for a in values(message, path)
                     if isinstance(a, str) and a != ""]
        return HandlerResult(self.table, row, children, addresses)


# Columns shared by several IBC messages
PROOF_HEIGHT = {
    "proof_height_revision_number": "proof_height.revision_number",
    "proof_height_revision_height": "proof_height.revision_height",
}
PACKET = {
    "sequence": "packet.sequence",
    "source_port": "packet.source_port",
    "source_channel": "packet.source_channel",
    "destination_port": "packet.destination_port",
    "destination_channel": "packet.destination_channel",
    "data": "packet.data",
    "timeout_height_revision_number": "packet.timeout_height.revision_number",
    "timeout_height_revision_height": "packet.timeout_height.revision_height",
    "timeout_timestamp": "packet.timeout_timestamp",
}
