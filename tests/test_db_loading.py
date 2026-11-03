"""loading_tx.py and verify_tx.py against a real PostgreSQL database.

Skipped unless INDEXER_TEST_DB_NAME is set (see tests/helpers.py). Transactions
are decoded from saved fixtures, so no network access is needed.

Bugs covered:
- Re-running a block attached every later transaction's messages to tx #1
  (the UniqueViolation fallback looked the transaction up by block_id).
- Blocks were looked up by height alone, ignoring chain_id.
- An unknown message type shifted the numbers of the messages after it.
- verify_tx.py exited 0 even when verification failed, crashed instead of
  reporting a missing row, and expected fee_denom "0" for transactions with
  no fee while loading_tx.py stores "".
"""
import copy
import tempfile
import unittest
from pathlib import Path

import helpers
from helpers import BlockLoader, messages_by_tx, query, requires_db

CHAIN_ID = "migaloo-1"


@requires_db
class DbTestCase(unittest.TestCase):
    def setUp(self):
        helpers.reset_db()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.workdir = helpers.make_workdir(tmp.name)

    def tx_hashes(self):
        """tx hashes in block order (comment holds the 1-based position)."""
        rows = query("SELECT tx_hash, comment FROM transactions WHERE height = %s", (helpers.BLOCK_HEIGHT,))
        return [h for h, _ in sorted(rows, key=lambda r: int(r[1].split()[3]))]


class RerunTest(DbTestCase):
    def test_rerun_keeps_messages_on_their_own_transaction(self):
        loader = BlockLoader(self.workdir)
        loader.load_all()
        first = messages_by_tx()

        loader.load_all()  # e.g. restarting after a crash
        second = messages_by_tx()

        self.assertEqual(second, first, "re-running a block must not add or move messages")
        tx1, tx2, tx3 = self.tx_hashes()
        self.assertEqual([t for t, _ in second[tx1]], ["cosmos_exec_msg"])
        self.assertEqual([t for t, _ in second[tx2]], ["ibc_acknowledgement_msg", "ibc_updateclient_msg"])
        self.assertEqual([t for t, _ in second[tx3]], ["cosmos_vote_msg"])


class ChainIdTest(DbTestCase):
    def test_transactions_attach_to_block_of_their_own_chain(self):
        # Another chain's block at the same height, inserted first
        query(
            "INSERT INTO blocks (block_hash, chain_id, height, tx_num, created_at) "
            "VALUES ('DECOY', 'other-chain-1', %s, '0', now())",
            (helpers.BLOCK_HEIGHT,),
        )
        loader = BlockLoader(self.workdir)
        loader.load_all()

        rows = query(
            "SELECT DISTINCT b.chain_id FROM transactions t JOIN blocks b ON b.block_id = t.block_id"
        )
        self.assertEqual(rows, [(CHAIN_ID,)])
        for i in range(3):
            code, _, err = loader.verify_tx(i)
            self.assertEqual(code, 0, err)


class MessageNumberingTest(DbTestCase):
    def test_unknown_type_does_not_shift_later_message_numbers(self):
        decoded = helpers.load_decoded()
        messages = decoded[1]["tx"]["body"]["messages"]  # [UpdateClient, Acknowledgement]
        messages.insert(1, {"@type": "/test.v1.MsgNotInTypeJson"})
        loader = BlockLoader(self.workdir, decoded=decoded)

        loader.load_all()

        comments = query("SELECT comment FROM ibc_acknowledgement_msg")
        self.assertEqual(len(comments), 1)
        self.assertTrue(comments[0][0].startswith("This is number 3 message"), comments[0][0])
        logged = (self.workdir / "log" / "new_type.txt").read_text()
        self.assertIn("No. 2 message in No. 2 transaction", logged)


class VerifyTxTest(DbTestCase):
    def test_correct_rows_pass(self):
        loader = BlockLoader(self.workdir)
        loader.load_all()
        for i in range(3):
            code, _, err = loader.verify_tx(i)
            self.assertEqual(code, 0, err)
            self.assertNotIn("Error in block", err)

    def test_mismatch_exits_nonzero(self):
        loader = BlockLoader(self.workdir)
        loader.load_all()
        query("UPDATE transactions SET memo = 'tampered' WHERE tx_hash = %s", (self.tx_hashes()[0],))

        code, _, err = loader.verify_tx(0)

        self.assertEqual(code, 1)
        self.assertIn("in column memo", err)

    def test_missing_row_is_reported(self):
        loader = BlockLoader(self.workdir)
        loader.load_block_row()  # block row only, no transactions

        code, _, err = loader.verify_tx(0)

        self.assertEqual(code, 1)
        self.assertIn("There should be only one row", err)
        self.assertNotIn("IndexError", err)

    def test_transaction_without_fee_passes(self):
        decoded = helpers.load_decoded()
        decoded[0]["tx"]["auth_info"]["fee"]["amount"] = []
        loader = BlockLoader(self.workdir, decoded=decoded)
        loader.load_all()

        code, _, err = loader.verify_tx(0)

        self.assertEqual(code, 0, err)
        self.assertNotIn("Error in block", err)


if __name__ == "__main__":
    unittest.main()
