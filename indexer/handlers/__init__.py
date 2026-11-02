"""Handler registry, loaded once from type.json (D2).

type.json maps each message type URL to a handler name. Every name must have a handler
and every handler must be named there: a mismatch fails at startup, not mid-run.
"""
import json
import os
from pathlib import Path
from typing import Optional

from . import authz, bank, gov_alliance, ibc, staking, wasm
from .spec import Handler, HandlerResult

DEFAULT_TYPE_JSON = Path(__file__).resolve().parents[2] / "type.json"
ALL_HANDLERS: list[Handler] = [
    *bank.HANDLERS, *authz.HANDLERS, *staking.HANDLERS, *gov_alliance.HANDLERS, *wasm.HANDLERS, *ibc.HANDLERS,
]


class Registry:
    def __init__(self, type_json: dict, handlers: list[Handler] = ALL_HANDLERS):
        by_name = {h.name: h for h in handlers}
        if len(by_name) != len(handlers):
            raise ValueError("two handlers share a name")
        missing = sorted(set(type_json.values()) - set(by_name))
        unused = sorted(set(by_name) - set(type_json.values()))
        if missing or unused:
            raise ValueError(f"type.json and the handlers disagree: no handler for {missing}, not in type.json {unused}")
        self._by_type = {}
        for type_url, name in type_json.items():
            handler = by_name[name]
            if handler.type_url != type_url:
                raise ValueError(f"type.json maps {type_url} to {name}, which handles {handler.type_url}")
            self._by_type[type_url] = handler

    def get(self, type_url: str) -> Optional[Handler]:
        return self._by_type.get(type_url)

    def handle(self, type_url: str, message: dict) -> Optional[HandlerResult]:
        """The typed row(s) for a message, or None when its type has no handler."""
        handler = self._by_type.get(type_url)
        return handler(message) if handler else None

    def type_urls(self) -> list:
        return sorted(self._by_type)


_registry: Optional[Registry] = None


def get_registry() -> Registry:
    global _registry
    if _registry is None:
        path = Path(os.environ.get("INDEXER_TYPE_JSON") or DEFAULT_TYPE_JSON)
        _registry = Registry(json.loads(path.read_text()))
    return _registry
