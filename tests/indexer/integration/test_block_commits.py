"""I1: a block commits completely or not at all."""
import json
from pathlib import Path

import pytest

from indexer import writer
from indexer.db import connect
from indexer.parse import parse_block
from indexer_support.invariants import check_invariants, counts

REPO = Path(__file__).resolve().parents[3]
MIGALOO = json.loads((REPO / "test_blocks" / "7027410").read_text())
DECODED = json.loads((REPO / "tests" / "fixtures" / "decoded" / "7027410.json").read_text())
BLOCK = parse_block(MIGALOO["block_id"], MIGALOO["block"], [d["tx"] for d in DECODED])


def test_valid_block_commits(clean_db):
    conn = connect(clean_db)
    try:
        writer.write_block(conn, BLOCK)
        assert counts(conn) == (1, 3, 4)
        check_invariants(conn)
    finally:
        conn.close()


def test_writing_a_block_twice_changes_nothing(clean_db):
    conn = connect(clean_db)
    try:
        first = writer.write_block(conn, BLOCK)
        second = writer.write_block(conn, BLOCK)
        assert first == second
        assert counts(conn) == (1, 3, 4)
        check_invariants(conn)
    finally:
        conn.close()


def test_failure_in_the_last_message_rolls_back_the_whole_block(clean_db, monkeypatch):
    real = writer.insert_message
    calls = []

    def failing(cur, tx_id, msg):
        calls.append(msg.index)
        if len(calls) == 4:  # the last of the block's 4 messages
            raise RuntimeError("boom")
        return real(cur, tx_id, msg)

    monkeypatch.setattr(writer, "insert_message", failing)
    conn = connect(clean_db)
    try:
        with pytest.raises(RuntimeError):
            writer.write_block(conn, BLOCK)
        assert counts(conn) == (0, 0, 0)
        check_invariants(conn)
    finally:
        conn.close()
