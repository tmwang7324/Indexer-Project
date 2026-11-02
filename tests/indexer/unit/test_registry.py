"""The handler registry refuses to start when type.json and the handlers disagree."""
import json
from dataclasses import replace

import pytest

from indexer.handlers import ALL_HANDLERS, DEFAULT_TYPE_JSON, Registry
from indexer.handlers.spec import get, values

TYPE_JSON = json.loads(DEFAULT_TYPE_JSON.read_text())


def test_matching_type_json_and_handlers_load():
    registry = Registry(TYPE_JSON)
    assert len(registry.type_urls()) == 35 and registry.get("/cosmos.bank.v1beta1.MsgSend").table == "cosmos_send_msg"


@pytest.mark.parametrize("break_it, message", [
    (lambda t, h: ({**t, "/x.MsgNew": "no_such_handler"}, h), "no handler for"),
    (lambda t, h: (t, h[1:]), "no handler for"),
    (lambda t, h: ({k: v for k, v in t.items() if v != "cosmos_send_msg"}, h), "not in type.json"),
    (lambda t, h: (t, [*h, h[0]]), "share a name"),
    (lambda t, h: (t, [replace(x, type_url="/other.Url") if x.name == "cosmos_send_msg" else x for x in h]),
     "which handles"),
], ids=["type.json names an unknown handler", "handler missing", "handler not in type.json",
        "duplicate handler", "wrong type URL"])
def test_inconsistent_registry_is_refused(break_it, message):
    type_json, handlers = break_it(dict(TYPE_JSON), list(ALL_HANDLERS))
    with pytest.raises(ValueError, match=message):
        Registry(type_json, handlers)


def test_path_helpers():
    doc = {"a": [{"b": "x"}, {"b": "y"}, {"c": 1}], "n": None}
    assert values(doc, "a[].b") == ["x", "y"]
    assert get(doc, "a.1.b") == "y" and get(doc, "a.7.b") is None
    assert get(doc, "n.x") is None and get(doc, "a.b") is None
