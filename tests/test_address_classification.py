"""address_load.classify_address.

Bug: the 'length after 1 >= 38' (contract) test came before '== 38' (user), so
the user branch was unreachable and every wallet address was labelled 'contract'.
"""
import contextlib
import io
import unittest

import helpers  # noqa: F401  (puts the repository on sys.path)
from address_load import classify_address

# Real addresses from the test blocks
USER = "migaloo194ytn50yhh67rdha8akhs7c6zulnz4n2yrqeed"              # 38 chars after '1'
VALIDATOR = "migaloovaloper16skk5gcmazhkv945gauuuhlugd099ltnf9qkey"
CONTRACT = "migaloo1" + "q" * 58                                      # 32-byte account
OTHER_CHAIN_USER = "osmo1" + "q" * 38


class ClassifyAddressTest(unittest.TestCase):
    def test_user_address(self):
        self.assertEqual(classify_address(USER), "user")

    def test_user_address_on_another_chain(self):
        self.assertEqual(classify_address(OTHER_CHAIN_USER), "user")

    def test_contract_address(self):
        self.assertEqual(classify_address(CONTRACT), "contract")

    def test_validator_address(self):
        self.assertEqual(classify_address(VALIDATOR), "validator")

    def test_blank_address(self):
        self.assertEqual(classify_address(""), "blank")

    def test_prefix_containing_1_uses_last_separator(self):
        # A prefix may contain '1'; the bech32 separator is the last '1'.
        self.assertEqual(classify_address("chain1x1" + "q" * 38), "user")

    def test_unknown_address_is_reported(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(classify_address("migaloo1short", "123"), "Unknown")
        self.assertIn("migaloo1short", err.getvalue())


if __name__ == "__main__":
    unittest.main()
