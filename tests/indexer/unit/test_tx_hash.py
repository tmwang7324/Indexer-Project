"""U2: a known transaction gives its known hash (SHA-256 of the raw bytes, uppercase hex)."""
import json
from pathlib import Path

import pytest

from indexer.errors import BadDataError
from indexer.parse import tx_hash

REPO = Path(__file__).resolve().parents[3]


def test_known_transaction_hash():
    block = json.loads((REPO / "test_blocks" / "7027410").read_text())
    raw = block["block"]["data"]["txs"][2]
    assert tx_hash(raw) == "E77D14CB104E70372F151F73C5C233A351C6A014B64A67F9BCA9E5EB7B445C20"


def test_invalid_base64_is_bad_data():
    with pytest.raises(BadDataError):
        tx_hash("not base64!!")
