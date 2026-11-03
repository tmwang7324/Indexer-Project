"""The Migaloo block 7027410 used by several tests."""
import json

from indexer.parse import parse_block

from .messages import DECODED, REPO

_BLOCK_FILE = json.loads((REPO / "test_blocks" / "7027410").read_text())
BLOCK = parse_block(_BLOCK_FILE["block_id"], _BLOCK_FILE["block"], [d["tx"] for d in DECODED])
BLOCK_FILE = _BLOCK_FILE
