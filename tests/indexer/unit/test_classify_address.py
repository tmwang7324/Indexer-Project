"""U4: classification by the length after the last '1', for any bech32 prefix."""
import pytest

from indexer.addresses import classify_address

CASES = {
    "user_migaloo": ("migaloo194ytn50yhh67rdha8akhs7c6zulnz4n2yrqeed", "user"),
    "user_terra": ("terra1t9wrfkpyawdmntrcxfda6339gmkg5kn0llejd3", "user"),
    "user_other_chain": ("osmo1" + "q" * 38, "user"),
    "contract": ("terra152qx935uyfwknm706mpvc3rqa9q2gtem2uzxq92q6ah5swwm25eslf3wkj", "contract"),
    "validator_migaloo": ("migaloovaloper16skk5gcmazhkv945gauuuhlugd099ltnf9qkey", "validator"),
    "validator_terra": ("terravaloper1c9ye54e3pzwm3e0zpdlel6pnavrj9qqv6e8r4h", "validator"),
    "blank": ("", "blank"),
    "unknown_too_short": ("terra1abc", "Unknown"),
    # the prefix itself contains a '1': the separator is the LAST one
    "prefix_containing_1": ("cosmos1x1" + "q" * 38, "user"),
}


@pytest.mark.parametrize("name", CASES)
def test_classify_address(name):
    address, expected = CASES[name]
    assert classify_address(address) == expected


def test_unknown_is_logged(caplog):
    classify_address("terra1abc")
    assert "could not classify address 'terra1abc'" in caplog.text
