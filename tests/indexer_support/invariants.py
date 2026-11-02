"""The shared invariant checker (Rule 3): call it at the end of every integration test."""


def check_invariants(conn) -> None:
    """Assert the database is consistent. Grows with each ticket.

    Now: every height is stored once, and no block is partly written.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT chain_id, height, count(*) FROM blocks GROUP BY chain_id, height HAVING count(*) > 1""")
        assert cur.fetchall() == [], "a height is stored more than once"

        cur.execute("""
            SELECT b.chain_id, b.height, b.tx_num, count(t.tx_id)
            FROM blocks b LEFT JOIN transactions t ON t.block_id = b.block_id
            GROUP BY b.block_id HAVING b.tx_num <> count(t.tx_id)""")
        assert cur.fetchall() == [], "blocks whose transaction rows do not match tx_num (partial blocks)"

        cur.execute("""
            SELECT t.chain_id, t.height, t.tx_index, jsonb_array_length(t.tx_info -> 'body' -> 'messages'),
                   count(m.message_id)
            FROM transactions t LEFT JOIN messages m ON m.tx_id = t.tx_id
            GROUP BY t.tx_id
            HAVING jsonb_array_length(t.tx_info -> 'body' -> 'messages') <> count(m.message_id)""")
        assert cur.fetchall() == [], "transactions whose message rows do not match their body (partial blocks)"
    conn.rollback()


def counts(conn):
    """(blocks, transactions, messages) row counts."""
    with conn.cursor() as cur:
        cur.execute("SELECT (SELECT count(*) FROM blocks), (SELECT count(*) FROM transactions), "
                    "(SELECT count(*) FROM messages)")
        row = cur.fetchone()
    conn.rollback()
    return row
