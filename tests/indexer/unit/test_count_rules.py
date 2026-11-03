"""U10: the count rules are a pure function (D14)."""
import pytest

from indexer.verify import Mismatch, Summary, check_counts

OK = Summary(transactions=3, outcomes=3, messages=5)


@pytest.mark.parametrize("written, expected", [
    (Summary(3, 3, 5), []),
    (Summary(2, 3, 5), [Mismatch("transactions", 3, 2)]),
    (Summary(4, 3, 5), [Mismatch("transactions", 3, 4)]),
    (Summary(3, 2, 5), [Mismatch("outcomes", 3, 2)]),
    (Summary(3, 3, 4), [Mismatch("messages", 5, 4)]),
    (Summary(2, 2, 3), [Mismatch("transactions", 3, 2), Mismatch("outcomes", 3, 2), Mismatch("messages", 5, 3)]),
], ids=["match", "missing tx", "extra tx", "missing outcome", "wrong message count", "several at once"])
def test_check_counts(written, expected):
    assert check_counts(OK, written) == expected


def test_a_source_without_outcomes_expects_none():
    """The Migaloo files have no /block_results: zero outcomes expected, zero stored."""
    assert check_counts(Summary(2, 0, 4), Summary(2, 0, 4)) == []
    assert check_counts(Summary(2, 0, 4), Summary(2, 1, 4)) == [Mismatch("outcomes", 0, 1)]


def test_mismatch_reads_as_a_sentence():
    assert str(Mismatch("messages", 5, 4)) == "messages: the source has 5, the database has 4"


def test_the_sample_depends_only_on_the_seed():
    from indexer.verify import pick_sample
    stored = [("phoenix-1", h) for h in range(100, 200)]
    assert pick_sample(stored, 5, seed=1) == pick_sample(list(reversed(stored)), 5, seed=1)
    assert pick_sample(stored, 5, seed=1) != pick_sample(stored, 5, seed=2)
    assert len(pick_sample(stored, 500, seed=1)) == 100       # asking for more than exist gives all
