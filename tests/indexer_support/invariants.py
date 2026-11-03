"""The shared invariant checker (Rule 3): call it at the end of every integration test."""


import threading

from indexer.handlers import get_registry
from indexer.pipeline import THREAD_PREFIX


def check_invariants(conn, pipeline=None) -> None:
    """Assert the database is consistent. Grows with each ticket.

    Now: every height is stored once or in failed_blocks, never both, no block is partly written, the checkpoint is the highest contiguous height, and every message of a handled type
    has its typed row.
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

        cur.execute("""
            SELECT f.chain_id, f.height FROM failed_blocks f
            JOIN blocks b ON b.chain_id = f.chain_id AND b.height = f.height""")
        assert cur.fetchall() == [], "a height is both stored and in failed_blocks"

        cur.execute("""
            SELECT c.chain_id, c.contiguous_height FROM checkpoints c
            JOIN blocks b ON b.chain_id = c.chain_id AND b.height = c.contiguous_height + 1""")
        assert cur.fetchall() == [], "the checkpoint is not the highest contiguous stored height"

        # every message of a handled type has its typed row
        for type_url in get_registry().type_urls():
            handler = get_registry().get(type_url)
            cur.execute(f"""SELECT m.message_id FROM messages m
                            WHERE m.type = %s AND NOT EXISTS
                                  (SELECT 1 FROM {handler.table} t WHERE t.message_id = m.message_id)""",
                        (type_url,))
            assert cur.fetchall() == [], f"{type_url} messages without a typed row"
    conn.rollback()
    # a finished run leaves nothing behind: every connection is back, every worker thread has ended
    alive = [t.name for t in threading.enumerate() if t.name.startswith(THREAD_PREFIX) and t.is_alive()]
    assert alive == [], f"worker threads still running: {alive}"
    if pipeline is not None and pipeline.pool is not None:
        assert pipeline.pool.in_use == 0, f"{pipeline.pool.in_use} pooled connection(s) were never returned"


def counts(conn):
    """(blocks, transactions, messages) row counts."""
    with conn.cursor() as cur:
        cur.execute("SELECT (SELECT count(*) FROM blocks), (SELECT count(*) FROM transactions), "
                    "(SELECT count(*) FROM messages)")
        row = cur.fetchone()
    conn.rollback()
    return row


def snapshot(conn) -> dict:
    """The database content with generated ids replaced by natural keys, for whole-output comparisons
    (Rule 5): two runs that should give the same result must give equal snapshots."""
    from indexer.handlers import ALL_HANDLERS

    def rows(cur, sql, params=()):
        cur.execute(sql, params)
        return sorted(tuple(str(v) for v in r) for r in cur.fetchall())

    snap = {}
    with conn.cursor() as cur:
        snap["blocks"] = rows(cur, "SELECT chain_id, height, block_hash, tx_num, created_at FROM blocks")
        snap["transactions"] = rows(cur, """
            SELECT chain_id, height, tx_index, tx_hash, memo, gas_limit, created_at, code, codespace,
                   gas_wanted, gas_used, log, events, tx_info FROM transactions""")
        snap["fees"] = rows(cur, """SELECT t.tx_hash, f.coin_index, f.denom, f.amount
                                    FROM transaction_fees f JOIN transactions t USING (tx_id)""")
        snap["messages"] = rows(cur, """SELECT t.tx_hash, m.msg_index, m.type, m.raw
                                        FROM messages m JOIN transactions t USING (tx_id)""")
        for h in ALL_HANDLERS:
            for table in (h.table, *h.side_tables):
                snap[table] = rows(cur, f"""SELECT t.tx_hash, m.msg_index, to_jsonb(x) - 'message_id'
                                            FROM {table} x JOIN messages m USING (message_id)
                                            JOIN transactions t USING (tx_id)""")
        snap["address"] = rows(cur, "SELECT value, address_type FROM address")
        snap["message_addresses"] = rows(cur, """
            SELECT t.tx_hash, m.msg_index, a.value, ma.role FROM message_addresses ma
            JOIN messages m USING (message_id) JOIN transactions t USING (tx_id)
            JOIN address a USING (address_id)""")
    conn.rollback()
    return snap


def diff_snapshots(a: dict, b: dict) -> str:
    """The rows that differ between two snapshots, table by table, for a readable failure message."""
    lines = []
    for table in sorted(set(a) | set(b)):
        only_a = [r for r in a.get(table, []) if r not in b.get(table, [])]
        only_b = [r for r in b.get(table, []) if r not in a.get(table, [])]
        if only_a or only_b:
            lines.append(f"{table}: {len(only_a)} row(s) only in the first, {len(only_b)} only in the second")
            lines += [f"  < {r}" for r in only_a[:5]] + [f"  > {r}" for r in only_b[:5]]
    return "\n".join(lines)
