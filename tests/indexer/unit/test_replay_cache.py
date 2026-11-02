"""U11: write then read returns the same bytes (D5)."""
import gzip

import pytest

from indexer.errors import BadDataError
from indexer.sources.replay import ReplayCache

TXS = b'{"txs":[],"pagination":{"next_key":"AQID","total":"0"}}'
PAGE2 = b'{"txs":[],"pagination":{"next_key":null,"total":"0"}}'
RESULTS = b'{"result":{"height":"5","txs_results":null}}\n'


def test_roundtrip_returns_the_same_bytes(tmp_path):
    cache = ReplayCache(tmp_path)
    assert cache.write("phoenix-1", 5, [TXS, PAGE2], RESULTS) is True
    pages, results = cache.read("phoenix-1", 5)
    assert pages == [TXS, PAGE2] and results == RESULTS
    assert (tmp_path / "phoenix-1" / "5.txs.1.json.gz").exists()
    assert cache.heights("phoenix-1") == [5]


def test_an_already_cached_block_is_not_written_again(tmp_path):
    cache = ReplayCache(tmp_path)
    cache.write("phoenix-1", 5, [TXS], RESULTS)
    first = (tmp_path / "phoenix-1" / "5.txs.json.gz").stat().st_mtime_ns
    assert cache.write("phoenix-1", 5, [b"different"], b"different") is False
    assert gzip.decompress((tmp_path / "phoenix-1" / "5.txs.json.gz").read_bytes()) == TXS
    assert (tmp_path / "phoenix-1" / "5.txs.json.gz").stat().st_mtime_ns == first


def test_same_bytes_give_the_same_file(tmp_path):
    a, b = ReplayCache(tmp_path / "a"), ReplayCache(tmp_path / "b")
    a.write("c", 1, [TXS], RESULTS)
    b.write("c", 1, [TXS], RESULTS)
    assert (tmp_path / "a/c/1.txs.json.gz").read_bytes() == (tmp_path / "b/c/1.txs.json.gz").read_bytes()


def test_missing_block_is_bad_data(tmp_path):
    with pytest.raises(BadDataError):
        ReplayCache(tmp_path).read("phoenix-1", 9)
