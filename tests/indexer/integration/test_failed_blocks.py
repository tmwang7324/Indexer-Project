"""I1[count_mismatch]: a block whose responses disagree leaves no rows and a failed_blocks row; the next block
still indexes (D14)."""
from dataclasses import replace

import pytest

from indexer import run, writer
from indexer.db import connect
from indexer.errors import CountMismatchError
from indexer_support.cache import CHAIN, copy_blocks
from indexer_support.invariants import check_invariants, counts
from indexer_support.sample import BLOCK

# three consecutive sample heights that all have transactions
H1, H2, H3 = 23561833, 23561834, 23561835


def drop_last_result(doc):
    (doc.get("result") or doc)["txs_results"].pop()


def query(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    conn.rollback()
    return rows


@pytest.fixture
def db(indexer_env):
    conn = connect(indexer_env)
    yield conn
    conn.close()


def test_a_block_with_one_result_fewer_is_recorded_and_the_next_block_still_indexes(db, indexer_env, tmp_path):
    cache = copy_blocks(tmp_path, [H1, H2, H3], results={H2: drop_last_result})
    assert run.main(["run", "--source", f"replay:{cache.root}"]) == run.EXIT_FAILED_BLOCKS

    assert [h for (h,) in query(db, "SELECT height FROM blocks ORDER BY height")] == [H1, H3]
    assert query(db, "SELECT count(*) FROM transactions WHERE height = %s", (H2,)) == [(0,)]
    [(chain, height, error, attempts)] = query(db, "SELECT chain_id, height, error, attempts FROM failed_blocks")
    assert (chain, height, attempts) == (CHAIN, H2, 1)
    assert "transactions but" in error and "results" in error
    check_invariants(db)


def test_a_count_mismatch_found_by_the_writer_rolls_the_block_back(db):
    """Two transactions with the same bytes: the second insert is skipped by ON CONFLICT, so the writer holds
    one transaction where the source has two. Nothing of the block may remain."""
    tx = BLOCK.transactions[0]
    twin = replace(tx, index=1)
    block = replace(BLOCK, transactions=[tx, twin])
    with pytest.raises(CountMismatchError, match="transactions: the source has 2, the database has 1"):
        writer.write_block(db, block)
    assert counts(db) == (0, 0, 0)
    check_invariants(db)


def test_a_later_success_removes_the_failure(db, indexer_env, tmp_path):
    bad = copy_blocks(tmp_path / "bad", [H2], results={H2: drop_last_result})
    assert run.main(["run", "--source", f"replay:{bad.root}"]) == run.EXIT_FAILED_BLOCKS
    assert query(db, "SELECT height FROM failed_blocks") == [(H2,)]

    good = copy_blocks(tmp_path / "good", [H2])
    assert run.main(["run", "--source", f"replay:{good.root}"]) == run.EXIT_OK
    assert query(db, "SELECT count(*) FROM failed_blocks") == [(0,)]
    assert query(db, "SELECT height FROM blocks") == [(H2,)]
    check_invariants(db)


def test_failing_again_counts_the_attempts(db, indexer_env, tmp_path):
    bad = copy_blocks(tmp_path, [H2], results={H2: drop_last_result})
    for _ in range(2):
        assert run.main(["run", "--source", f"replay:{bad.root}"]) == run.EXIT_FAILED_BLOCKS
    assert query(db, "SELECT attempts FROM failed_blocks") == [(2,)]


def test_a_corrupt_cache_file_is_bad_data_for_that_height(db, indexer_env, tmp_path):
    cache = copy_blocks(tmp_path, [H1, H2])
    (cache.root / CHAIN / f"{H1}.results.json.gz").write_bytes(b"not gzip")
    assert run.main(["run", "--source", f"replay:{tmp_path}"]) == run.EXIT_FAILED_BLOCKS
    assert query(db, "SELECT height FROM blocks") == [(H2,)]
    [(error,)] = query(db, "SELECT error FROM failed_blocks WHERE height = %s", (H1,))
    assert "cannot be read" in error
