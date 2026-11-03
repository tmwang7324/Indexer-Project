"""C2 (a checkpoint written twice is one row) and the cases of U6 (nothing done; in order; a gap; the gap filled).

The contiguous height is computed by the database inside the block's transaction (REVAMP.md section 9), so
the cases run against real PostgreSQL."""
import pytest

from indexer.checkpoint import advance_checkpoint, read_checkpoint, resolve_start

CHAIN = "test-1"


def store(cur, *heights, chain=CHAIN):
    for h in heights:
        cur.execute("INSERT INTO blocks (chain_id, height, block_hash, tx_num, created_at) "
                    "VALUES (%s, %s, 'AA', 0, now())", (chain, h))


@pytest.fixture
def cur(conn):
    with conn.cursor() as cur:
        yield cur


def test_nothing_done_the_checkpoint_stays_at_the_base(cur):
    assert read_checkpoint(cur, CHAIN) is None
    assert advance_checkpoint(cur, CHAIN, base=99) == 99
    assert read_checkpoint(cur, CHAIN) == 99


def test_blocks_in_order_move_it_one_by_one(cur):
    for h in (100, 101, 102):
        store(cur, h)
        assert advance_checkpoint(cur, CHAIN, base=99) == h


def test_a_gap_holds_it_back_and_filling_the_gap_moves_it_through_the_blocks_above(cur):
    store(cur, 100, 101, 102)
    assert advance_checkpoint(cur, CHAIN, base=99) == 102
    store(cur, 105)                                  # 103 and 104 are missing
    assert advance_checkpoint(cur, CHAIN, base=99) == 102
    store(cur, 106, 104)
    assert advance_checkpoint(cur, CHAIN, base=99) == 102
    store(cur, 103)                                  # the gap is filled: through 104, 105, 106
    assert advance_checkpoint(cur, CHAIN, base=99) == 106


def test_the_checkpoint_never_moves_back_and_the_base_only_creates_the_row(cur):
    store(cur, 100, 101)
    assert advance_checkpoint(cur, CHAIN, base=99) == 101
    assert advance_checkpoint(cur, CHAIN, base=50) == 101      # a lower base on a later run changes nothing
    assert advance_checkpoint(cur, CHAIN, base=99) == 101      # advancing twice is harmless


def test_a_checkpoint_written_twice_is_one_row(cur):
    store(cur, 100)
    advance_checkpoint(cur, CHAIN, base=99)
    advance_checkpoint(cur, CHAIN, base=99)
    cur.execute("SELECT chain_id, contiguous_height FROM checkpoints")
    assert cur.fetchall() == [(CHAIN, 100)]


def test_each_chain_has_its_own_checkpoint(cur):
    store(cur, 100, chain="a-1")
    store(cur, 7, 8, chain="b-1")
    assert advance_checkpoint(cur, "a-1", base=99) == 100
    assert advance_checkpoint(cur, "b-1", base=6) == 8
    assert read_checkpoint(cur, "a-1") == 100


def test_a_run_starts_above_the_checkpoint_or_at_from_height(conn):
    assert resolve_start(conn, CHAIN, 500) == 500          # no checkpoint yet
    assert resolve_start(conn, CHAIN, None) is None
    with conn.cursor() as cur:
        store(cur, 100)
        advance_checkpoint(cur, CHAIN, base=99)
    assert resolve_start(conn, CHAIN, 500) == 101          # the checkpoint wins over --from-height
