"""load_transactions.sh, with a stub 'python3' on PATH that records how each
script was called and exits with a chosen code.

Skipped unless INDEXER_TEST_DB_NAME is set (the script runs Txs.sql with psql)
and psql and jq are installed.

Bugs covered:
- psql was hard-coded to localhost and ignored db_host/db_port from info.json.
- loading_tx.py's exit status was never checked.
- Error messages printed "$?" after a [[ ]] test, i.e. the test's status rather
  than the script's exit code.
- $txt was never exported, so loading_tx.py could not find the log folder.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import helpers
from helpers import REPO, requires_db

STUB = """#!/bin/bash
# Records the script name and $txt, then exits with STUB_EXIT if the script
# name matches STUB_FAIL_SCRIPT.
echo "$1 txt=${txt-UNSET}" >> "$STUB_RECORD"
if [[ "$1" == "$STUB_FAIL_SCRIPT" ]]; then
    exit "$STUB_EXIT"
fi
exit 0
"""


@requires_db
@unittest.skipUnless(shutil.which("psql") and shutil.which("jq"), "needs psql and jq")
class LoadTransactionsShTest(unittest.TestCase):
    def setUp(self):
        helpers.reset_db()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "bin").mkdir()
        stub = self.root / "bin" / "python3"
        stub.write_text(STUB)
        stub.chmod(0o755)
        (self.root / "blocks").mkdir()
        shutil.copy(helpers.BLOCK_FILE, self.root / "blocks" / helpers.BLOCK_HEIGHT)
        (self.root / "work").mkdir()
        self.record = self.root / "record.txt"
        self.record.touch()

    def run_sh(self, db=None, fail_script="", exit_code=3):
        workdir = helpers.make_workdir(self.root / "work", db)
        env = dict(
            os.environ,
            PATH=f"{self.root / 'bin'}:{os.environ['PATH']}",
            STUB_RECORD=str(self.record),
            STUB_FAIL_SCRIPT=fail_script,
            STUB_EXIT=str(exit_code),
        )
        env.pop("txt", None)
        return subprocess.run(
            ["bash", str(REPO / "load_transactions.sh"), "-t",
             "-b", str(self.root / "blocks"), "-o", str(self.root / "log")],
            cwd=workdir, env=env, capture_output=True, text=True, timeout=120,
        )

    def test_uses_port_from_info_json(self):
        db = dict(helpers.db_config(), db_port="1")  # nothing listens on port 1
        result = self.run_sh(db=db)
        self.assertEqual(result.returncode, 9, result.stdout + result.stderr)

    def test_exports_log_folder_to_python_scripts(self):
        result = self.run_sh()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.record.read_text().splitlines()
        loading_tx_calls = [c for c in calls if c.startswith("loading_tx.py")]
        self.assertEqual(len(loading_tx_calls), 3)
        for call in loading_tx_calls:
            self.assertEqual(call, f"loading_tx.py txt={self.root / 'log'}")

    def test_loading_tx_failure_is_reported_with_its_exit_code(self):
        result = self.run_sh(fail_script="loading_tx.py", exit_code=3)
        self.assertIn("Transaction 0 in 7027410 loading into database failed. (Exit code 3)", result.stderr)
        self.assertIn("3 transactions failed to load or verify.", result.stdout)
        calls = self.record.read_text()
        self.assertNotIn("verify_tx.py", calls, "a transaction that failed to load should not be verified")

    def test_verify_tx_failure_is_reported_with_its_exit_code(self):
        result = self.run_sh(fail_script="verify_tx.py", exit_code=3)
        self.assertIn("Transaction 0 in 7027410 does not pass the verification test. (Exit code 3)", result.stderr)
        self.assertIn("3 transactions failed to load or verify.", result.stdout)


if __name__ == "__main__":
    unittest.main()
