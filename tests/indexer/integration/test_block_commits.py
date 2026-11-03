"""I1: a block commits completely or not at all."""
import copy

import pytest

from indexer import writer
from indexer.db import connect
from indexer.parse import parse_block
from indexer_support.invariants import check_invariants, counts
from indexer_support.messages import DECODED
from indexer_support.sample import BLOCK, BLOCK_FILE


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


def test_unknown_message_type_is_stored_without_a_typed_copy(clean_db):
    """The block is indexed; the unknown message is a `messages` row only (D2)."""
    infos = copy.deepcopy([d["tx"] for d in DECODED])
    infos[2]["body"]["messages"][0]["@type"] = "/some.future.MsgThing"
    block = parse_block(BLOCK_FILE["block_id"], BLOCK_FILE["block"], infos)
    conn = connect(clean_db)
    try:
        writer.write_block(conn, block)
        assert counts(conn) == (1, 3, 4)
        with conn.cursor() as cur:
            cur.execute("SELECT type FROM messages WHERE type = '/some.future.MsgThing'")
            assert cur.fetchall() == [("/some.future.MsgThing",)]
            cur.execute("SELECT count(*) FROM cosmos_exec_msg")
            assert cur.fetchone() == (1,)   # the rest of the block is typed as usual
            cur.execute("SELECT count(*) FROM cosmos_vote_msg")
            assert cur.fetchone() == (0,)
        conn.rollback()
        check_invariants(conn)
    finally:
        conn.close()


def test_an_address_used_in_several_messages_is_stored_once(clean_db):
    """The relayer signs both messages of transaction 1: one address row, two links with the same role."""
    relayer = "migaloo18xrruhq5r246mwk0yj9elnn3mte8xa9udpjhej"
    conn = connect(clean_db)
    try:
        writer.write_block(conn, BLOCK)
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM address WHERE value = %s", (relayer,))
            assert cur.fetchone() == (1,)
            cur.execute("""SELECT m.type, ma.role FROM message_addresses ma
                           JOIN address a USING (address_id) JOIN messages m USING (message_id)
                           WHERE a.value = %s ORDER BY m.msg_index""", (relayer,))
            assert cur.fetchall() == [("/ibc.core.client.v1.MsgUpdateClient", "signer"),
                                      ("/ibc.core.channel.v1.MsgAcknowledgement", "signer")]
        conn.rollback()
        check_invariants(conn)
    finally:
        conn.close()
