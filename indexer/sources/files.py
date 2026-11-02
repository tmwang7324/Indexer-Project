"""Files source: block files from a folder plus their decoded transactions.

A block file is the JSON a node returns for /cosmos/base/tendermint/v1beta1/blocks/{h}.
Its transactions are raw bytes; the decoded JSON comes from a saved file:
  1. <block file>.decoded.json next to the block file, or
  2. <decoded dir>/<height>.json (default: tests/fixtures/decoded).
A block with no decoded file is reported and skipped until local decoding exists (D26).
"""
import json
import logging
import os
from pathlib import Path
from typing import Iterator, Optional

from ..errors import BadDataError
from ..models import Block
from ..parse import parse_block

log = logging.getLogger(__name__)

DEFAULT_DECODED_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "decoded"


class FilesSource:
    def __init__(self, folder, decoded_dir: Optional[Path] = None):
        self.folder = Path(folder)
        self.decoded_dir = Path(decoded_dir or os.environ.get("INDEXER_DECODED_DIR") or DEFAULT_DECODED_DIR)
        self.skipped: list[str] = []

    def _decoded_for(self, path: Path, height: str) -> Optional[Path]:
        for candidate in (path.with_name(path.name + ".decoded.json"),
                          path.with_name(f"{height}.decoded.json"),
                          self.decoded_dir / f"{height}.json"):
            if candidate.is_file():
                return candidate
        return None

    def blocks(self) -> Iterator[Block]:
        for path in sorted(p for p in self.folder.iterdir() if p.is_file() and not p.name.endswith(".decoded.json")):
            try:
                content = json.loads(path.read_text())
                height = content["block"]["header"]["height"]
            except (ValueError, KeyError, TypeError) as exc:
                raise BadDataError(f"{path} is not a block file: {exc!r}") from exc
            txs = content["block"]["data"].get("txs") or []
            decoded_path = self._decoded_for(path, height) if txs else None
            if txs and decoded_path is None:
                log.warning("skipping %s: raw transaction bytes and no decoded file", path.name)
                self.skipped.append(path.name)
                continue
            decoded = json.loads(decoded_path.read_text()) if decoded_path else []
            yield parse_block(content["block_id"], content["block"], [d["tx"] for d in decoded])
