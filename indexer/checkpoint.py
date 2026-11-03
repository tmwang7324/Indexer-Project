"""The checkpoint: the highest height H such that every block from the run's first height up to H is stored (D7).

It is derived from the `blocks` rows themselves, inside the database transaction of the block that extends it,
so it can never run ahead of what is stored. Blocks can arrive in any order (ticket 08): a block above a gap
leaves the checkpoint where it is, and the block that fills the gap moves it through every consecutive stored
height after it. Transactions serialise on the checkpoint's row, so the last one to commit sees all the others.
"""
from typing import Optional


def read_checkpoint(conn_or_cur, chain_id: str) -> Optional[int]:
    """The stored checkpoint, or None before the first block of the chain was written."""
    def read(cur):
        cur.execute("SELECT contiguous_height FROM checkpoints WHERE chain_id = %s", (chain_id,))
        row = cur.fetchone()
        return row[0] if row else None

    if hasattr(conn_or_cur, "cursor"):
        with conn_or_cur.cursor() as cur:
            value = read(cur)
        conn_or_cur.rollback()
        return value
    return read(conn_or_cur)


def advance_checkpoint(cur, chain_id: str, base: int) -> int:
    """Move the checkpoint as far as the stored blocks allow, on an open transaction. Returns the new value.

    `base` is the height just below the run's first block; it creates the row if the chain has none yet.
    The walk visits one row per height it passes and stops at the first gap, so a missing block makes
    the cost of every later call a single lookup.
    """
    cur.execute("INSERT INTO checkpoints (chain_id, contiguous_height) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (chain_id, base))
    cur.execute("SELECT contiguous_height FROM checkpoints WHERE chain_id = %s FOR UPDATE", (chain_id,))
    current = cur.fetchone()[0]
    cur.execute(
        """WITH RECURSIVE run(h) AS (
               SELECT %s::bigint
               UNION ALL
               SELECT b.height FROM run JOIN blocks b ON b.chain_id = %s AND b.height = run.h + 1)
           SELECT max(h) FROM run""", (current, chain_id))
    new = cur.fetchone()[0]
    if new > current:
        cur.execute("UPDATE checkpoints SET contiguous_height = %s, updated_at = now() WHERE chain_id = %s",
                    (new, chain_id))
    return new


def resolve_start(conn, chain_id: str, from_height: Optional[int]) -> Optional[int]:
    """Where a run begins: one above the checkpoint if the chain has one, otherwise --from-height."""
    done = read_checkpoint(conn, chain_id)
    return done + 1 if done is not None else from_height
