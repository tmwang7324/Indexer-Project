"""U5: every handler maps its message to the expected typed row, side rows and addresses.

Messages: the 4 types that occur in the Migaloo fixtures come from there; the others are hand-written
(tests/indexer/data/handler_messages.json) because the curated sample can't contain every type (D24).
Expected output lives in handler_expected.json; regenerate it deliberately with `pytest --update-golden`
and review the diff.
"""
import json
from pathlib import Path

import pytest

from indexer.handlers import get_registry
from indexer_support.messages import MESSAGES

DATA = Path(__file__).resolve().parents[1] / "data"
EXPECTED_FILE = DATA / "handler_expected.json"

TYPES = get_registry().type_urls()


def test_every_handler_has_a_case():
    assert sorted(MESSAGES) == TYPES and len(TYPES) == 35


def _as_json(result):
    return json.loads(json.dumps({"table": result.table, "row": result.row,
                                  "children": result.children, "addresses": result.addresses}))


@pytest.mark.parametrize("type_url", TYPES, ids=lambda t: t.rsplit(".", 1)[-1] + ":" + t.split(".")[0].lstrip("/"))
def test_handler_maps_message(type_url, request):
    actual = _as_json(get_registry().handle(type_url, MESSAGES[type_url]))
    if request.config.getoption("--update-golden"):
        expected = json.loads(EXPECTED_FILE.read_text()) if EXPECTED_FILE.exists() else {}
        expected[type_url] = actual
        EXPECTED_FILE.write_text(json.dumps(dict(sorted(expected.items())), indent=1, ensure_ascii=False) + "\n")
    assert actual == json.loads(EXPECTED_FILE.read_text())[type_url]


def test_unknown_type_has_no_handler():
    assert get_registry().handle("/some.future.MsgThing", {"@type": "/some.future.MsgThing"}) is None
