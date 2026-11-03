"""The `verify` command over a stored run: exit 0 when nothing differs, non-zero and a line per difference
when a field was changed by hand (D14)."""
import pytest

from indexer import run
from indexer.db import connect
from indexer_support.db import REPO

SAMPLE = REPO / "tests" / "indexer" / "data" / "terra"


@pytest.fixture
def stored(indexer_env):
    assert run.main(["run", "--source", f"replay:{SAMPLE}"]) == 0
    return indexer_env


def test_nothing_differs_exits_zero(stored, capsys):
    assert run.main(["verify", "--sample", "50", "--seed", "7", "--source", f"replay:{SAMPLE}"]) == 0
    out = capsys.readouterr().out
    assert "seed 7" in out and "0 difference(s)" in out


def test_a_field_changed_by_hand_is_reported(stored, capsys):
    conn = connect(stored)
    with conn.cursor() as cur:
        cur.execute("UPDATE transactions SET memo = 'edited by hand' WHERE tx_id = (SELECT min(tx_id) FROM transactions)")
        cur.execute("SELECT height, tx_index FROM transactions WHERE memo = 'edited by hand'")
        height, index = cur.fetchone()
    conn.commit()
    conn.close()
    assert run.main(["verify", "--sample", "50", "--seed", "7", "--source", f"replay:{SAMPLE}"]) == 1
    out = capsys.readouterr().out
    assert f"{height} / transactions[{index}] / memo: 'edited by hand' != " in out
    assert "1 difference(s)" in out
